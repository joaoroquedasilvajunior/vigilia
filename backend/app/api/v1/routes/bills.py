from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Bill

router = APIRouter(prefix="/bills", tags=["bills"])


@router.get("")
async def list_bills(
    db: Annotated[AsyncSession, Depends(get_db)],
    type: str | None = Query(None, description="PL | PEC | MPV | PDL"),
    status: str | None = Query(None),
    theme: str | None = Query(None, description="Theme slug, e.g. meio-ambiente"),
    high_risk: bool | None = Query(None, description="Filter bills with const_risk_score > 0.6"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    q = select(Bill)
    if type:
        q = q.where(Bill.type == type.upper())
    if status:
        q = q.where(Bill.status.ilike(f"%{status}%"))
    if theme:
        q = q.where(Bill.theme_tags.any(theme))
    if high_risk is True:
        q = q.where(Bill.const_risk_score > 0.6)
    elif high_risk is False:
        q = q.where((Bill.const_risk_score <= 0.6) | Bill.const_risk_score.is_(None))

    q = q.order_by(Bill.presentation_date.desc().nullslast())

    total_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = total_result.scalar_one()

    result = await db.execute(q.offset((page - 1) * page_size).limit(page_size))
    bills = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_bill(b) for b in bills],
    }


@router.get("/{bill_id}")
async def get_bill(
    bill_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Bill).where(Bill.id == bill_id))
    bill = result.scalar_one_or_none()
    if not bill:
        raise HTTPException(404, "Projeto de lei não encontrado")
    return _serialize_bill(bill, full=True)


def _serialize_bill(b: Bill, *, full: bool = False) -> dict:
    data = {
        "id": str(b.id),
        "camara_id": b.camara_id,
        "type": b.type,
        "number": b.number,
        "year": b.year,
        "title": b.title,
        "status": b.status,
        "urgency_regime": b.urgency_regime,
        "secrecy_vote": b.secrecy_vote,
        "const_risk_score": b.const_risk_score,
        "theme_tags": b.theme_tags,
        "presentation_date": b.presentation_date,
    }
    if full:
        data.update({
            "summary_official": b.summary_official,
            "summary_ai": b.summary_ai,
            "full_text_url": b.full_text_url,
            "affected_articles": b.affected_articles,
            "final_vote_date": b.final_vote_date,
        })
    return data
