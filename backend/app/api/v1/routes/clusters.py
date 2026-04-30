"""
Read endpoints for behavioral clusters.
Cluster compute is triggered via POST /sync/clusters in routes/sync.py.
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import BehavioralCluster, Legislator, Party

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("")
async def list_clusters(db: Annotated[AsyncSession, Depends(get_db)]):
    """
    All behavioral clusters with their stats and party distribution.
    Returns one row per cluster sorted by member_count DESC.
    """
    # Pull clusters
    cluster_rows = (
        await db.execute(
            select(BehavioralCluster).order_by(BehavioralCluster.member_count.desc())
        )
    ).scalars().all()

    if not cluster_rows:
        return {"clusters": [], "note": "No clusters computed yet — POST /sync/clusters."}

    # Pull party distribution per cluster in one query
    party_rows = (
        await db.execute(
            select(
                Legislator.behavioral_cluster_id,
                Party.acronym,
                func.count(Legislator.id).label("n"),
            )
            .outerjoin(Party, Legislator.nominal_party_id == Party.id)
            .where(Legislator.behavioral_cluster_id.is_not(None))
            .group_by(Legislator.behavioral_cluster_id, Party.acronym)
        )
    ).all()

    party_dist: dict[str, dict[str, int]] = {}
    for r in party_rows:
        cid = str(r.behavioral_cluster_id)
        party_dist.setdefault(cid, {})[r.acronym or "(sem partido)"] = r.n

    # Top 6 members per cluster (single query via ROW_NUMBER window)
    member_preview = await db.execute(text("""
        SELECT cluster_id, id, name, state_uf, photo_url, party_acronym
        FROM (
            SELECT
                l.behavioral_cluster_id::text AS cluster_id,
                l.id::text                    AS id,
                COALESCE(l.display_name, l.name) AS name,
                l.state_uf,
                l.photo_url,
                p.acronym AS party_acronym,
                ROW_NUMBER() OVER (
                    PARTITION BY l.behavioral_cluster_id
                    ORDER BY COALESCE(l.display_name, l.name)
                ) AS rn
            FROM legislators l
            LEFT JOIN parties p ON l.nominal_party_id = p.id
            WHERE l.behavioral_cluster_id IS NOT NULL
        ) sub
        WHERE rn <= 6
        ORDER BY cluster_id, rn
    """))
    top_members: dict[str, list[dict]] = {}
    for r in member_preview.all():
        top_members.setdefault(r.cluster_id, []).append({
            "id":            r.id,
            "name":          r.name,
            "state_uf":      r.state_uf,
            "photo_url":     r.photo_url,
            "party_acronym": r.party_acronym,
        })

    return {
        "clusters": [
            {
                "id":               str(c.id),
                "label":            c.label,
                "description":      c.description,
                "dominant_themes":  c.dominant_themes,
                "member_count":     c.member_count,
                "cohesion_score":   c.cohesion_score,
                "algorithm":        c.algorithm,
                "algorithm_params": c.algorithm_params,
                "computed_at":      c.computed_at.isoformat() if c.computed_at else None,
                "party_distribution": party_dist.get(str(c.id), {}),
                "top_members":        top_members.get(str(c.id), []),
            }
            for c in cluster_rows
        ]
    }


@router.get("/{cluster_id}/members")
async def cluster_members(
    cluster_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """List legislators in a specific cluster, with party + state."""
    rows = (
        await db.execute(
            select(Legislator, Party)
            .outerjoin(Party, Legislator.nominal_party_id == Party.id)
            .where(Legislator.behavioral_cluster_id == cluster_id)
            .order_by(Legislator.state_uf, Legislator.display_name)
        )
    ).all()
    # Also load the cluster header so the page can render the title
    cluster_row = (
        await db.execute(
            select(BehavioralCluster).where(BehavioralCluster.id == cluster_id)
        )
    ).scalar_one_or_none()

    return {
        "cluster_id":     cluster_id,
        "cluster_label":  cluster_row.label if cluster_row else None,
        "member_count":   cluster_row.member_count if cluster_row else len(rows),
        "cohesion_score": cluster_row.cohesion_score if cluster_row else None,
        "members": [
            {
                "id":        str(leg.id),
                "name":      leg.display_name or leg.name,
                "state_uf":  leg.state_uf,
                "party":     party.acronym if party else None,
                "photo_url": leg.photo_url,
            }
            for leg, party in rows
        ],
    }
