"""
Aggregations behind the /analises page.

Each endpoint returns a small, denormalized payload purpose-built for one
visualization — keeping client code free of joins/post-processing. Pure
read-only; no auth required.
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
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
