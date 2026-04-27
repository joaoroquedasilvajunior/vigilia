"""
Read endpoints for behavioral clusters.
Cluster compute is triggered via POST /sync/clusters in routes/sync.py.
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
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
    return {
        "cluster_id": cluster_id,
        "members": [
            {
                "id":           str(leg.id),
                "name":         leg.display_name or leg.name,
                "state_uf":     leg.state_uf,
                "party":        party.acronym if party else None,
            }
            for leg, party in rows
        ],
    }
