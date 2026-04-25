from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
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
    q = select(Legislator)
    if state:
        q = q.where(Legislator.state_uf == state.upper())
    if chamber:
        q = q.where(Legislator.chamber == chamber)
    if party:
        q = q.join(Party, Legislator.nominal_party_id == Party.id).where(
            func.upper(Party.acronym) == party.upper()
        )

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()

    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    legislators = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_legislator(l) for l in legislators],
    }


@router.get("/{legislator_id}")
async def get_legislator(
    legislator_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Legislator).where(Legislator.id == legislator_id))
    legislator = result.scalar_one_or_none()
    if not legislator:
        raise HTTPException(404, "Legislador não encontrado")
    return _serialize_legislator(legislator)


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


def _serialize_legislator(l: Legislator) -> dict:
    return {
        "id": str(l.id),
        "camara_id": l.camara_id,
        "name": l.name,
        "display_name": l.display_name,
        "chamber": l.chamber,
        "state_uf": l.state_uf,
        "photo_url": l.photo_url,
        "const_alignment_score": l.const_alignment_score,
        "party_discipline_score": l.party_discipline_score,
        "absence_rate": l.absence_rate,
    }
