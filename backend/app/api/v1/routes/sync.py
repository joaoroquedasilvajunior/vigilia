"""
Internal sync trigger endpoints.
In production these are called by GitHub Actions cron; guarded by a shared secret.
"""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException

from app.core.config import settings
from app.ingestion.sync_pipeline import (
    sync_high_profile_bills_votes,
    sync_legislators,
    sync_recent_bills,
    sync_votes_for_bill,
)
from app.ingestion.tag_pipeline import tag_bills
from app.ingestion.tse_pipeline import sync_donors

router = APIRouter(prefix="/sync", tags=["sync"])

_SYNC_SECRET = settings.supabase_service_role_key  # re-use as internal secret for now


def _verify_secret(x_sync_secret: Annotated[str | None, Header()] = None) -> None:
    if settings.environment == "development":
        return
    if not _SYNC_SECRET or x_sync_secret != _SYNC_SECRET:
        raise HTTPException(401, "Invalid sync secret")


@router.post("/legislators")
async def trigger_sync_legislators(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    background_tasks.add_task(sync_legislators)
    return {"status": "queued", "job": "sync_legislators"}


@router.post("/bills")
async def trigger_sync_bills(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
    days_back: int = 7,
):
    background_tasks.add_task(sync_recent_bills, days_back=days_back)
    return {"status": "queued", "job": "sync_recent_bills", "days_back": days_back}


@router.post("/bills/{camara_bill_id}/votes")
async def trigger_sync_votes(
    camara_bill_id: int,
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    background_tasks.add_task(sync_votes_for_bill, camara_bill_id)
    return {"status": "queued", "job": "sync_votes_for_bill", "camara_bill_id": camara_bill_id}


@router.post("/donors")
async def trigger_sync_donors(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """Download TSE 2022 candidate accounts and upsert donors + donor_links."""
    background_tasks.add_task(sync_donors)
    return {"status": "queued", "job": "sync_donors"}


@router.post("/tags")
async def trigger_tag_bills(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """Tag all untagged bills with theme slugs using claude-haiku-4-5."""
    background_tasks.add_task(tag_bills)
    return {"status": "queued", "job": "tag_bills"}


@router.post("/votes/high-profile")
async def trigger_sync_high_profile_votes(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """Pull votes for the curated HIGH_PROFILE_BILL_CAMARA_IDS list.
    Bills not yet in the DB are fetched from the Câmara API first.
    """
    background_tasks.add_task(sync_high_profile_bills_votes)
    return {"status": "queued", "job": "sync_high_profile_bills_votes"}
