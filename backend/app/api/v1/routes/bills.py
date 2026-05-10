from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
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


@router.get("/featured")
async def featured_bills(
    db: Annotated[AsyncSession, Depends(get_db)],
    ids: str = Query(..., description="Comma-separated camara_ids"),
):
    """
    Bulk fetch for the homepage "Em Destaque" section. Returns each
    bill plus a vote breakdown in a single SQL query — avoids the
    6-roundtrip pattern the frontend would otherwise need.

    Items are returned in the same order as the requested ids.
    Missing bills appear with {"camara_id": N, "not_in_db": True}.
    """
    camara_ids = [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
    if not camara_ids:
        return {"items": []}

    rows = (await db.execute(text("""
        SELECT
            b.id, b.camara_id, b.type, b.number, b.year,
            b.title, b.status,
            b.const_risk_score, b.theme_tags,
            COUNT(v.id) FILTER (WHERE v.vote_value = 'sim')        AS votes_sim,
            COUNT(v.id) FILTER (WHERE v.vote_value = 'não')        AS votes_nao,
            COUNT(v.id) FILTER (WHERE v.vote_value = 'abstencao')  AS votes_abstencao,
            COUNT(v.id) FILTER (WHERE v.vote_value = 'obstrucao')  AS votes_obstrucao,
            COUNT(v.id) FILTER (WHERE v.vote_value = 'ausente')    AS votes_ausente,
            COUNT(v.id)                                             AS votes_total
        FROM bills b
        LEFT JOIN votes v ON v.bill_id = b.id
        WHERE b.camara_id = ANY(:ids)
        GROUP BY b.id
    """), {"ids": camara_ids})).all()
    by_id = {r.camara_id: dict(r._mapping) for r in rows}

    items = []
    for cid in camara_ids:
        if cid in by_id:
            d = by_id[cid]
            d["id"] = str(d["id"])
            items.append(d)
        else:
            items.append({"camara_id": cid, "not_in_db": True})
    return {"items": items}


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


# ── Vote breakdown ──────────────────────────────────────────────────────────
# Powers the "Votação no Plenário" section on each bill detail page. Returns
# the bucket totals plus the full list of "não" voters with party/UF/cluster
# so the page can render an "X deputados que votaram NÃO" disclosure — the
# headline question for high-profile bills (Dosimetria, etc).

_BILL_VOTES_SQL = text("""
SELECT
    v.vote_value,
    COUNT(*)                         AS count,
    COALESCE(
        ARRAY_AGG(
            JSON_BUILD_OBJECT(
                'id',       l.id::text,
                'name',     COALESCE(l.display_name, l.name),
                'party',    p.acronym,
                'state',    l.state_uf,
                'cluster',  bc.label,
                'photo_url', l.photo_url
            ) ORDER BY p.acronym NULLS LAST, COALESCE(l.display_name, l.name)
        ) FILTER (WHERE v.vote_value = 'não'),
        '{}'
    ) AS nao_voters
FROM votes v
JOIN legislators l ON v.legislator_id = l.id
LEFT JOIN parties p ON l.nominal_party_id = p.id
LEFT JOIN behavioral_clusters bc ON l.behavioral_cluster_id = bc.id
WHERE v.bill_id = :bill_id
GROUP BY v.vote_value
""")


def _status_outcome(status: str | None) -> str:
    """Same status→outcome map used by the homepage card. The Câmara status
    is the source of truth for whether a bill became law — a multi-turn PEC
    can have nao>sim in our votes table because we keep last-vote-per-deputy
    while the bill itself was approved across destaques."""
    if not status:
        return "pending"
    s = status.lower()
    if any(k in s for k in ("transformad", "promulgad", "sancionad", "convertid", "aprovad")):
        return "approved"
    if any(k in s for k in ("rejeit", "arquiv")):
        return "rejected"
    return "pending"


@router.get("/{bill_id}/votes")
async def get_bill_votes(
    bill_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    bill_row = (await db.execute(select(Bill).where(Bill.id == bill_id))).scalar_one_or_none()
    if not bill_row:
        raise HTTPException(404, "Projeto de lei não encontrado")

    rows = (await db.execute(_BILL_VOTES_SQL, {"bill_id": bill_id})).all()

    # Pivot vote_value rows into a flat summary, plus pull the "não" list out
    # of whichever row carried it (the array_agg(... FILTER) guarantees only
    # the 'não' row's array is non-empty — every other row gets an empty array).
    summary = {"sim": 0, "não": 0, "abstencao": 0, "obstrucao": 0, "ausente": 0}
    nao_voters: list[dict] = []
    for r in rows:
        if r.vote_value in summary:
            summary[r.vote_value] = r.count
        if r.nao_voters and len(r.nao_voters) > 0:
            nao_voters = list(r.nao_voters)

    total = sum(summary.values())
    sim = summary["sim"]
    nao = summary["não"]
    other = summary["abstencao"] + summary["obstrucao"] + summary["ausente"]

    return {
        "bill_id":        str(bill_id),
        "outcome":        _status_outcome(bill_row.status),
        "status":         bill_row.status,
        "summary": {
            "sim":         sim,
            "não":         nao,
            "abstencao":   summary["abstencao"],
            "obstrucao":   summary["obstrucao"],
            "ausente":     summary["ausente"],
            "other":       other,
            "total":       total,
        },
        "nao_voters":     nao_voters,
    }


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
