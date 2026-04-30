"""Lightweight homepage stats — total counts for hero section."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import BehavioralCluster, Bill, Legislator, Vote

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
async def get_stats(db: Annotated[AsyncSession, Depends(get_db)]):
    """One row of counts for the homepage hero stats bar."""
    rows = await db.execute(
        select(
            select(func.count()).select_from(Legislator).scalar_subquery().label("legislators"),
            select(func.count()).select_from(Bill).scalar_subquery().label("bills"),
            select(func.count()).select_from(Vote).scalar_subquery().label("votes"),
            select(func.count()).select_from(BehavioralCluster).scalar_subquery().label("clusters"),
        )
    )
    r = rows.one()
    return {
        "legislators": r.legislators,
        "bills":       r.bills,
        "votes":       r.votes,
        "clusters":    r.clusters,
    }
