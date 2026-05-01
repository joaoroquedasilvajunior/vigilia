from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Legislator, Party, Vote, Bill

router = APIRouter(prefix="/legislators", tags=["legislators"])


@router.get("")
async def list_legislators(
    db: Annotated[AsyncSession, Depends(get_db)],
    state: str | None = Query(None, description="Filter by UF (e.g. SP, RJ)"),
    party: str | None = Query(None, description="Filter by party acronym"),
    chamber: str | None = Query(None, description="camara | senado"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    q = select(Legislator, Party).outerjoin(Party, Legislator.nominal_party_id == Party.id)
    if state:
        q = q.where(Legislator.state_uf == state.upper())
    if chamber:
        q = q.where(Legislator.chamber == chamber)
    if party:
        q = q.where(func.upper(Party.acronym) == party.upper())

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()

    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_legislator(l, p) for l, p in rows],
    }


@router.get("/{legislator_id}")
async def get_legislator(
    legislator_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Legislator, Party)
        .outerjoin(Party, Legislator.nominal_party_id == Party.id)
        .where(Legislator.id == legislator_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, "Legislador não encontrado")
    legislator, party = row
    return _serialize_legislator(legislator, party)


@router.get("/{legislator_id}/votes")
async def get_legislator_votes(
    legislator_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    q = (
        select(Vote, Bill)
        .join(Bill, Vote.bill_id == Bill.id)
        .where(Vote.legislator_id == legislator_id)
        .order_by(Vote.voted_at.desc().nullslast())
    )
    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()

    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    rows = result.all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "vote_value": vote.vote_value,
                "voted_at": vote.voted_at,
                "followed_party_line": vote.followed_party_line,
                "donor_conflict_flag": vote.donor_conflict_flag,
                "const_conflict_flag": vote.const_conflict_flag,
                "bill": {
                    "id": str(bill.id),
                    "type": bill.type,
                    "number": bill.number,
                    "year": bill.year,
                    "title": bill.title,
                    "status": bill.status,
                    "const_risk_score": bill.const_risk_score,
                    "theme_tags": bill.theme_tags,
                },
            }
            for vote, bill in rows
        ],
    }


# ── Donor exposure ────────────────────────────────────────────────────────
# Sector → relevant bill themes mapping. Source: spec.
# When sector_group becomes reliable across the donor table, this map drives
# the correlation calculation per legislator. Until then, most sectors will
# return zero matches because all donors are classified "outros".
_SECTOR_TO_THEMES: dict[str, list[str]] = {
    "agronegocio":   ["agronegocio", "meio-ambiente", "indigenas"],
    "financeiro":    ["tributacao"],
    "construtoras":  ["reforma-politica", "tributacao"],
    "religioso":     ["religiao", "direitos-lgbtqia"],
    "armas":         ["armas", "seguranca-publica"],
    "saude":         ["saude"],
    "educacao":      ["educacao"],
    "midia":         ["midia"],
    "energia-mineracao": ["meio-ambiente", "indigenas"],
}


@router.get("/{legislator_id}/donors")
async def get_legislator_donors(
    legislator_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """
    Donor exposure for one deputy: funding-source breakdown,
    sector breakdown, top named donors, and donor↔vote correlations
    where the spec's sector→theme map has matching data.
    """
    # 1. Funding source breakdown (party fund / individual / company).
    # This is the breakdown that ALWAYS has real signal in current data —
    # 86% of campaign money is FEFC party-fund transfers post-2015.
    funding = (await db.execute(text("""
        WITH classified AS (
            SELECT
                CASE
                    WHEN UPPER(d.name) LIKE '%DIREÇÃO%'
                      OR UPPER(d.name) LIKE '%DIRECAO%' THEN 'party_fund'
                    WHEN d.entity_type = 'pessoa_fisica' THEN 'individual'
                    WHEN d.entity_type = 'pessoa_juridica' THEN 'company'
                    ELSE 'other'
                END AS bucket,
                dl.amount_brl,
                d.id AS donor_id
            FROM donor_links dl
            JOIN donors d ON dl.donor_id = d.id
            WHERE dl.legislator_id = :leg_id
        )
        SELECT
            bucket,
            COUNT(DISTINCT donor_id) AS donor_count,
            SUM(amount_brl)::float    AS total_brl
        FROM classified
        GROUP BY bucket
        ORDER BY total_brl DESC
    """), {"leg_id": str(legislator_id)})).all()
    funding_breakdown = [
        {"bucket": r.bucket, "donor_count": r.donor_count, "total_brl": r.total_brl}
        for r in funding
    ]
    total_received = sum(r["total_brl"] for r in funding_breakdown)

    # 2. Sector breakdown — top 8 sector_groups by total. Most rows will be
    # "outros" today; the section is structurally ready for when sector
    # classification is fixed.
    sectors = (await db.execute(text("""
        SELECT
            d.sector_group,
            COUNT(DISTINCT d.id)        AS donor_count,
            SUM(dl.amount_brl)::float    AS total_brl,
            (
                SELECT array_agg(name ORDER BY total DESC) FILTER (WHERE rn <= 5)
                FROM (
                    SELECT d2.name, SUM(dl2.amount_brl) AS total,
                           ROW_NUMBER() OVER (ORDER BY SUM(dl2.amount_brl) DESC) AS rn
                    FROM donor_links dl2
                    JOIN donors d2 ON dl2.donor_id = d2.id
                    WHERE dl2.legislator_id = :leg_id
                      AND d2.sector_group = d.sector_group
                      AND UPPER(d2.name) NOT LIKE '%DIREÇÃO%'
                      AND UPPER(d2.name) NOT LIKE '%DIRECAO%'
                    GROUP BY d2.name
                ) sub
            ) AS top_donor_names
        FROM donor_links dl
        JOIN donors d ON dl.donor_id = d.id
        WHERE dl.legislator_id = :leg_id
        GROUP BY d.sector_group
        ORDER BY total_brl DESC
        LIMIT 8
    """), {"leg_id": str(legislator_id)})).all()
    sector_breakdown = [
        {
            "sector": r.sector_group,
            "donor_count": r.donor_count,
            "total_brl": r.total_brl,
            "top_donor_names": [n for n in (r.top_donor_names or []) if n],
        }
        for r in sectors
    ]

    # 3. Top 5 named individual donors (excluding party-fund transfers,
    # which aren't "named donors" in any meaningful civic-intelligence sense).
    top_donors_rows = (await db.execute(text("""
        SELECT d.name, d.sector_group, d.entity_type,
               SUM(dl.amount_brl)::float AS total_brl
        FROM donor_links dl
        JOIN donors d ON dl.donor_id = d.id
        WHERE dl.legislator_id = :leg_id
          AND UPPER(d.name) NOT LIKE '%DIREÇÃO%'
          AND UPPER(d.name) NOT LIKE '%DIRECAO%'
        GROUP BY d.id, d.name, d.sector_group, d.entity_type
        ORDER BY total_brl DESC
        LIMIT 5
    """), {"leg_id": str(legislator_id)})).all()
    top_donors = [
        {
            "name": r.name,
            "sector": r.sector_group,
            "entity_type": r.entity_type,
            "total_brl": r.total_brl,
        }
        for r in top_donors_rows
    ]

    # 4. Donor ↔ vote correlations. For each sector with non-trivial
    # spending (≥ R$ 5 000) AND a known theme map AND non-party-fund money,
    # count how this deputy voted on bills tagged with the mapped themes.
    correlations: list[dict] = []
    for sec in sector_breakdown:
        sector = sec["sector"]
        if sector not in _SECTOR_TO_THEMES:
            continue
        # We only count NON-party-fund money so the bond between $$ and
        # vote behaviour is meaningful (party transfers don't imply
        # sector-level capture).
        non_pf_amount = (await db.execute(text("""
            SELECT COALESCE(SUM(dl.amount_brl), 0)::float AS amount
            FROM donor_links dl
            JOIN donors d ON dl.donor_id = d.id
            WHERE dl.legislator_id = :leg_id
              AND d.sector_group = :sector
              AND UPPER(d.name) NOT LIKE '%DIREÇÃO%'
              AND UPPER(d.name) NOT LIKE '%DIRECAO%'
        """), {"leg_id": str(legislator_id), "sector": sector})).scalar()
        if not non_pf_amount or non_pf_amount < 5000:
            continue

        themes = _SECTOR_TO_THEMES[sector]
        votes_row = (await db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE v.vote_value = 'sim')        AS sim,
                COUNT(*) FILTER (WHERE v.vote_value = 'não')        AS nao,
                COUNT(*) FILTER (WHERE v.vote_value = 'abstencao')  AS abstencao,
                COUNT(*) FILTER (WHERE v.vote_value = 'ausente')    AS ausente,
                COUNT(*)                                             AS total
            FROM votes v
            JOIN bills b ON v.bill_id = b.id
            WHERE v.legislator_id = :leg_id
              AND b.theme_tags && :themes
        """), {"leg_id": str(legislator_id), "themes": themes})).one()

        correlations.append({
            "sector": sector,
            "amount_brl": float(non_pf_amount),
            "themes": themes,
            "votes": {
                "sim":       votes_row.sim,
                "nao":       votes_row.nao,
                "abstencao": votes_row.abstencao,
                "ausente":   votes_row.ausente,
                "total":     votes_row.total,
            },
        })

    return {
        "legislator_id":     str(legislator_id),
        "total_received_brl": total_received,
        "funding_breakdown": funding_breakdown,
        "sector_breakdown":  sector_breakdown,
        "top_donors":        top_donors,
        "correlations":      correlations,
    }


def _serialize_legislator(l: Legislator, p: Party | None = None) -> dict:
    return {
        "id": str(l.id),
        "camara_id": l.camara_id,
        "name": l.name,
        "display_name": l.display_name,
        "chamber": l.chamber,
        "state_uf": l.state_uf,
        "photo_url": l.photo_url,
        "party_acronym": p.acronym if p else None,
        "behavioral_cluster_id": str(l.behavioral_cluster_id) if l.behavioral_cluster_id else None,
        "const_alignment_score": l.const_alignment_score,
        "party_discipline_score": l.party_discipline_score,
        "absence_rate": l.absence_rate,
    }
