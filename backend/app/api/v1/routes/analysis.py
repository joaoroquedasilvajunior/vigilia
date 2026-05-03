"""
Aggregations behind the /analises page.

Each endpoint returns a small, denormalized payload purpose-built for one
visualization — keeping client code free of joins/post-processing. Pure
read-only; no auth required.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import BehavioralCluster, Legislator, Party

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/scatter-discipline-alignment")
async def scatter_discipline_alignment(db: Annotated[AsyncSession, Depends(get_db)]):
    """
    One row per deputy with both score axes filled in. Used by the
    "Disciplina vs Alinhamento CF/88" scatter plot. Filters out anyone
    missing either score so the chart never has to draw at (null, null).
    """
    rows = (
        await db.execute(
            select(
                Legislator.id,
                Legislator.display_name,
                Legislator.name,
                Legislator.state_uf,
                Legislator.party_discipline_score,
                Legislator.const_alignment_score,
                Legislator.absence_rate,
                Party.acronym.label("party"),
                BehavioralCluster.id.label("cluster_id"),
                BehavioralCluster.label.label("cluster_label"),
            )
            .outerjoin(Party, Legislator.nominal_party_id == Party.id)
            .outerjoin(
                BehavioralCluster,
                Legislator.behavioral_cluster_id == BehavioralCluster.id,
            )
            .where(Legislator.party_discipline_score.is_not(None))
            .where(Legislator.const_alignment_score.is_not(None))
        )
    ).all()

    return {
        "items": [
            {
                "id":             str(r.id),
                "name":           r.display_name or r.name,
                "state_uf":       r.state_uf,
                "party":          r.party,
                "cluster_id":     str(r.cluster_id) if r.cluster_id else None,
                "cluster_label":  r.cluster_label,
                "discipline":     r.party_discipline_score,
                "const_alignment": r.const_alignment_score,
                "absence_rate":   r.absence_rate,
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ── Heatmap: donor sector × bill theme ───────────────────────────────────────
# Cell value = % of "sim" votes among (sim+não) cast by deputies who received
# corporate donations from that sector, on bills tagged with that theme.
#
# We exclude sector_group in ('outros', 'campanha', 'partido') because:
#   - "outros" is unclassified noise
#   - "campanha" / "partido" are intra-system flows (campaign committees and
#     party funds funneling money), not external sectors trying to influence
#     legislation
# We require entity_type='pessoa_juridica' so individual donations don't dilute
# the sector signal — those are handled in a separate viz.
#
# HAVING n_votes > 10 keeps the cell sample size meaningful; below that the
# pct is statistical noise.

_HEATMAP_SQL = text("""
WITH donor_deputies AS (
    SELECT DISTINCT dl.legislator_id, d.sector_group
    FROM donor_links dl
    JOIN donors d ON dl.donor_id = d.id
    WHERE d.sector_group IS NOT NULL
      AND d.sector_group NOT IN ('outros', 'campanha', 'partido')
      AND d.entity_type = 'pessoa_juridica'
),
themed_votes AS (
    SELECT
        v.legislator_id,
        v.vote_value,
        unnest(b.theme_tags) AS theme
    FROM votes v
    JOIN bills b ON v.bill_id = b.id
    WHERE b.theme_tags IS NOT NULL
      AND v.vote_value IN ('sim', 'não')
),
cells AS (
    SELECT
        dd.sector_group,
        tv.theme,
        COUNT(*) FILTER (WHERE tv.vote_value = 'sim')      AS sim_count,
        COUNT(*) FILTER (WHERE tv.vote_value = 'não')      AS nao_count,
        COUNT(*)                                            AS total_votes,
        COUNT(DISTINCT dd.legislator_id)                    AS deputy_count
    FROM donor_deputies dd
    JOIN themed_votes tv ON dd.legislator_id = tv.legislator_id
    GROUP BY dd.sector_group, tv.theme
    -- Both gates: enough votes (statistical signal) AND enough distinct
    -- deputies (so a single prolific voter can't dominate a cell). Without
    -- the deputy floor, "religioso" surfaced 90% sim rates that were
    -- actually one deputy's individual voting record projected onto the
    -- whole sector.
    HAVING COUNT(*) > 10
       AND COUNT(DISTINCT dd.legislator_id) >= 3
)
SELECT
    sector_group,
    theme,
    sim_count,
    nao_count,
    total_votes,
    deputy_count,
    ROUND(sim_count::numeric / NULLIF(total_votes, 0) * 100, 1) AS pct_sim
FROM cells
ORDER BY sector_group, theme
""")


@router.get("/donor-vote-heatmap")
async def donor_vote_heatmap(
    db: Annotated[AsyncSession, Depends(get_db)],
    top_themes: int = Query(8, ge=1, le=30),
):
    """
    Donor-sector × bill-theme heatmap. Returns:
      - cells: every (sector, theme) pair passing the >10-vote threshold
      - sectors: rows present in the result, ordered by total deputy_count DESC
      - themes:  the top-N themes by total votes across all sectors

    The frontend renders cells in a sectors × themes grid; pairs missing from
    `cells` should be drawn as empty (insufficient data).
    """
    rows = (await db.execute(_HEATMAP_SQL)).mappings().all()
    cells = [
        {
            "sector": r["sector_group"],
            "theme":  r["theme"],
            "sim":    r["sim_count"],
            "nao":    r["nao_count"],
            "total":  r["total_votes"],
            "deputies": r["deputy_count"],
            "pct_sim": float(r["pct_sim"]) if r["pct_sim"] is not None else None,
        }
        for r in rows
    ]

    # Rank sectors by deputies (max across themes — represents the sector's reach)
    sector_reach: dict[str, int] = {}
    for c in cells:
        sector_reach[c["sector"]] = max(sector_reach.get(c["sector"], 0), c["deputies"])
    sectors = sorted(sector_reach.keys(), key=lambda s: -sector_reach[s])

    # Rank themes by total votes across sectors
    theme_volume: dict[str, int] = {}
    for c in cells:
        theme_volume[c["theme"]] = theme_volume.get(c["theme"], 0) + c["total"]
    themes = sorted(theme_volume.keys(), key=lambda t: -theme_volume[t])[:top_themes]

    # Drop cells whose theme didn't make the top-N (so client can draw a clean grid)
    theme_set = set(themes)
    cells = [c for c in cells if c["theme"] in theme_set]

    return {
        "sectors": sectors,
        "themes":  themes,
        "cells":   cells,
    }


# ── State profiles (UF map) ──────────────────────────────────────────────────
# Per-state breakdown for the Brazil-tile-grid map. Combines:
#   - deputy distribution across behavioral clusters
#   - averaged behavioral indicators (const alignment, discipline, absence)
#   - top-5 deputies per UF (by const_alignment_score, NULLs last)
#   - party list per UF
# Returned in a single denormalized payload so the client doesn't need to
# refetch when the user clicks a state.

_STATE_CLUSTER_SQL = text("""
SELECT
    l.state_uf                          AS uf,
    bc.id::text                          AS cluster_id,
    bc.label                             AS cluster_label,
    COUNT(l.id)                          AS deputy_count,
    AVG(l.const_alignment_score)         AS avg_const,
    AVG(l.party_discipline_score)        AS avg_discipline,
    AVG(l.absence_rate)                  AS avg_absence
FROM legislators l
LEFT JOIN behavioral_clusters bc ON l.behavioral_cluster_id = bc.id
WHERE l.state_uf IS NOT NULL
GROUP BY l.state_uf, bc.id, bc.label
ORDER BY l.state_uf, deputy_count DESC
""")

_STATE_PARTIES_SQL = text("""
SELECT l.state_uf AS uf, ARRAY_AGG(DISTINCT p.acronym) FILTER (WHERE p.acronym IS NOT NULL) AS parties
FROM legislators l
LEFT JOIN parties p ON l.nominal_party_id = p.id
WHERE l.state_uf IS NOT NULL
GROUP BY l.state_uf
""")

_STATE_TOP_DEPUTIES_SQL = text("""
SELECT uf, id, name, photo_url, party, cluster_label, const_alignment_score
FROM (
    SELECT
        l.state_uf                                AS uf,
        l.id::text                                AS id,
        COALESCE(l.display_name, l.name)          AS name,
        l.photo_url                               AS photo_url,
        p.acronym                                 AS party,
        bc.label                                  AS cluster_label,
        l.const_alignment_score                   AS const_alignment_score,
        ROW_NUMBER() OVER (
            PARTITION BY l.state_uf
            ORDER BY l.const_alignment_score DESC NULLS LAST,
                     COALESCE(l.display_name, l.name)
        ) AS rn
    FROM legislators l
    LEFT JOIN parties p ON l.nominal_party_id = p.id
    LEFT JOIN behavioral_clusters bc ON l.behavioral_cluster_id = bc.id
    WHERE l.state_uf IS NOT NULL
) sub
WHERE rn <= 5
ORDER BY uf, rn
""")


@router.get("/state-profiles")
async def state_profiles(db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Per-UF aggregation for the Brazil map. Returns one row per state
    with cluster distribution, averaged scores, party list, and top-5
    deputies (by constitutional alignment).

    The "dominant cluster" is the one with the largest deputy count;
    if the largest is < 40% of the state's delegation we mark the
    state as "mixed" so it doesn't get falsely attributed.
    """
    cluster_rows = (await db.execute(_STATE_CLUSTER_SQL)).mappings().all()
    party_rows   = (await db.execute(_STATE_PARTIES_SQL)).mappings().all()
    top_rows     = (await db.execute(_STATE_TOP_DEPUTIES_SQL)).mappings().all()

    # Index parties by UF
    parties_by_uf: dict[str, list[str]] = {
        r["uf"]: list(r["parties"] or []) for r in party_rows
    }
    # Index top deputies by UF
    top_by_uf: dict[str, list[dict]] = {}
    for r in top_rows:
        top_by_uf.setdefault(r["uf"], []).append({
            "id":            r["id"],
            "name":          r["name"],
            "photo_url":     r["photo_url"],
            "party":         r["party"],
            "cluster_label": r["cluster_label"],
            "const_alignment": (
                float(r["const_alignment_score"])
                if r["const_alignment_score"] is not None else None
            ),
        })

    # Pivot cluster rows into per-UF aggregates
    by_uf: dict[str, dict] = {}
    for r in cluster_rows:
        uf = r["uf"]
        st = by_uf.setdefault(uf, {
            "uf": uf,
            "deputy_count": 0,
            "clusters": [],         # ordered by deputy_count DESC
            "const_sum": 0.0,
            "const_n":   0,
            "discipline_sum": 0.0,
            "discipline_n":   0,
            "absence_sum": 0.0,
            "absence_n":   0,
        })
        n = r["deputy_count"]
        st["deputy_count"] += n
        st["clusters"].append({
            "cluster_id":    r["cluster_id"],
            "cluster_label": r["cluster_label"] or "Sem cluster",
            "deputy_count":  n,
        })
        # Averages: weight per cluster's average by its count, then
        # divide once at the end. This recovers the population mean
        # (not a mean-of-means).
        if r["avg_const"] is not None:
            st["const_sum"] += float(r["avg_const"]) * n
            st["const_n"]   += n
        if r["avg_discipline"] is not None:
            st["discipline_sum"] += float(r["avg_discipline"]) * n
            st["discipline_n"]   += n
        if r["avg_absence"] is not None:
            st["absence_sum"] += float(r["avg_absence"]) * n
            st["absence_n"]   += n

    items: list[dict] = []
    for uf, st in by_uf.items():
        # Dominant cluster: top one if it commands ≥40% of the delegation.
        # Sort first to be safe (cluster_rows already ordered, but explicit).
        st["clusters"].sort(key=lambda c: -c["deputy_count"])
        top = st["clusters"][0] if st["clusters"] else None
        dominant: str | None = None
        if top and st["deputy_count"] > 0:
            share = top["deputy_count"] / st["deputy_count"]
            if share >= 0.40 and top["cluster_label"] != "Sem cluster":
                dominant = top["cluster_label"]
            else:
                dominant = "Misto"

        items.append({
            "uf":             uf,
            "deputy_count":   st["deputy_count"],
            "dominant_cluster": dominant,
            "clusters":       st["clusters"],
            "avg_const_alignment": (
                st["const_sum"] / st["const_n"] if st["const_n"] else None
            ),
            "avg_discipline": (
                st["discipline_sum"] / st["discipline_n"] if st["discipline_n"] else None
            ),
            "avg_absence": (
                st["absence_sum"] / st["absence_n"] if st["absence_n"] else None
            ),
            "parties":        sorted(parties_by_uf.get(uf, [])),
            "top_deputies":   top_by_uf.get(uf, []),
        })

    items.sort(key=lambda s: s["uf"])
    return {"items": items, "total": len(items)}
