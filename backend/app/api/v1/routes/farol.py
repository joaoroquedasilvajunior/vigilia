from typing import Annotated

import anthropic
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.farol.chat import farol_chat
from app.farol.classifier import classify_query
from app.farol.session import new_session

router = APIRouter(prefix="/farol", tags=["farol"])

# Module-level client — reuses the connection pool across requests
_anthropic_client = anthropic.AsyncAnthropic()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    sources: list[dict]
    session_id: str


@router.post("/classify")
async def classify(body: ChatRequest) -> dict:
    """Debug endpoint — returns raw classifier output for a query."""
    result = await classify_query(body.message, _anthropic_client)
    return {
        "category": result.category,
        "entities": {
            "legislator_name": result.legislator_name,
            "state_uf": result.state_uf,
            "theme_slug": result.theme_slug,
            "bill_type": result.bill_type,
            "bill_number": result.bill_number,
            "bill_year": result.bill_year,
            "keyword": result.keyword,
        },
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatResponse:
    sid = body.session_id or new_session()

    response_text, sources = await farol_chat(
        message=body.message,
        session_id=sid,
        db=db,
        client=_anthropic_client,
    )

    return ChatResponse(response=response_text, sources=sources, session_id=sid)
