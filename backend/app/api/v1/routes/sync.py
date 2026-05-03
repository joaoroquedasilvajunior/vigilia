"""
Internal sync trigger endpoints.
In production these are called by GitHub Actions cron; guarded by a shared secret.
"""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.ingestion.sync_pipeline import (
    backfill_urgency_for_voted_bills,
    sync_all_voted_bills,
    sync_high_profile_bills_votes,
    sync_legislators,
    sync_recent_bills,
    sync_votes_for_bill,
    sync_votes_principal_for_bills,
)
from app.analysis.clustering import compute_clusters
from app.analysis.constitutional_scorer import run_constitutional_pipeline
from app.analysis.party_discipline import compute_discipline_and_absence
from app.ingestion.orientation_pipeline import sync_party_orientations
from app.ingestion.tag_pipeline import tag_bills
from app.ingestion.tse_pipeline import (
    enrich_donors_cnpj,
    inspect_donors_csv,
    reclassify_donors,
    reclassify_donors_by_name,
    sync_donors,
)

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


@router.post("/constitutional")
async def trigger_constitutional_scoring(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """
    Score every unscored voted bill via Haiku for constitutional risk,
    then recompute legislators.const_alignment_score from those scores.
    Estimated runtime: ~8-15 minutes for ~330 bills.
    """
    background_tasks.add_task(run_constitutional_pipeline)
    return {"status": "queued", "job": "constitutional_scoring"}


@router.post("/orientations")
async def trigger_sync_orientations(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """
    Backfill votes.party_orientation from Câmara /votacoes/{id}/orientacoes.
    Required prerequisite for /sync/discipline. ~6-10 min runtime.
    """
    background_tasks.add_task(sync_party_orientations)
    return {"status": "queued", "job": "sync_party_orientations"}


@router.post("/discipline")
async def trigger_compute_discipline(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """
    Compute legislators.party_discipline_score, legislators.absence_rate,
    and parties.cohesion_score in pure SQL. Run after /sync/orientations.
    """
    background_tasks.add_task(compute_discipline_and_absence)
    return {"status": "queued", "job": "compute_discipline"}


@router.post("/clusters")
async def trigger_compute_clusters(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """Run k-means behavioral clustering on the legislator vote matrix."""
    background_tasks.add_task(compute_clusters)
    return {"status": "queued", "job": "compute_clusters"}


@router.post("/donors/reclassify")
async def trigger_reclassify_donors(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """
    Pattern-match donor names against known company / institution
    patterns and update donors.sector_group accordingly. Only touches
    rows where sector_group is currently NULL or 'outros'. donor_links
    untouched. Idempotent. ~10-30 s runtime — pure name matching, no
    network fetches.

    NOTE: this replaces the original TSE-fetching reclassify path
    because TSE's CDN persistently 403s from Railway. The CNAE-based
    reclassify_donors function is preserved in tse_pipeline.py for
    when network access is restored.
    """
    background_tasks.add_task(reclassify_donors_by_name)
    return {"status": "queued", "job": "reclassify_donors_by_name"}


@router.post("/enrich-donors")
async def trigger_enrich_donors(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """
    BrasilAPI-driven CNPJ enrichment for the ~400 corporate donors
    currently classified 'outros'. Re-downloads TSE 2022 receitas to
    recover raw CNPJs (which we never store; only their hashes), then
    calls https://brasilapi.com.br/api/cnpj/v1/{cnpj} for each match
    and writes the resulting sector_group back to donors.

    Rate-limited to 1 req/sec to BrasilAPI; cached so duplicate CNPJs
    don't re-hit the API. Estimated runtime ~7 minutes.

    Will fail with 403 if TSE blocks the Railway IP — that's a
    transient block, retry later.
    """
    background_tasks.add_task(enrich_donors_cnpj)
    return {
        "status": "queued",
        "job": "enrich_donors_cnpj",
        "estimated_minutes": 7,
    }


@router.post("/donors/reclassify-tse")
async def trigger_reclassify_donors_tse(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """Original CNAE-based reclassify (re-fetches TSE). Currently 403s."""
    background_tasks.add_task(reclassify_donors)
    return {"status": "queued", "job": "reclassify_donors_tse"}


@router.post("/donors/inspect")
async def trigger_inspect_donors_csv(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """Diagnostic — log TSE 2022 receitas CSV column headers (no DB writes)."""
    background_tasks.add_task(inspect_donors_csv)
    return {"status": "queued", "job": "inspect_donors_csv"}


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


@router.post("/votes/all")
async def trigger_sync_all_voted_bills(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
    date_start: str = "2023-02-01",
    date_end: str | None = None,
):
    """
    Sync votes for every bill that had a plenary vote in the window.
    Estimated runtime: 2-4+ hours for the full 2023-2024 legislature.
    Idempotent: bills with existing votes are skipped on retry.
    """
    background_tasks.add_task(
        sync_all_voted_bills, date_start=date_start, date_end=date_end,
    )
    return {
        "status": "queued",
        "job": "sync_all_voted_bills",
        "date_start": date_start,
        "date_end": date_end,
    }


class FixPrincipalReq(BaseModel):
    camara_ids: list[int] = Field(..., min_length=1, max_length=100)


@router.post("/votes/fix-principal")
async def trigger_fix_principal_votes(
    req: FixPrincipalReq,
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """
    Re-sync the listed bills using ONLY their principal voting session
    (texto-base / redação final / turno único). Wipes prior destaque-
    derived votes for each bill before reinserting. Use this to repair
    bills whose stored placar is misleading because the ingester picked
    up destaques instead of the bill's own approval.
    """
    background_tasks.add_task(sync_votes_principal_for_bills, req.camara_ids)
    return {
        "status": "queued",
        "job": "sync_votes_principal_for_bills",
        "n_bills": len(req.camara_ids),
        "camara_ids": req.camara_ids,
    }


@router.post("/backfill-urgency")
async def trigger_backfill_urgency(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """
    One-shot backfill of urgency_regime for every bill that has votes.
    The Câmara LIST endpoint omits statusProposicao entirely, so existing
    rows ingested via sync_recent_bills carry urgency_regime=false even
    when reality says otherwise. This walks every voted bill and refetches
    via the DETAIL endpoint, where regime is populated. Runtime ≈ 5-8 min
    at the conservative ~1.4s/bill pace.
    """
    background_tasks.add_task(backfill_urgency_for_voted_bills)
    return {
        "status": "queued",
        "job": "backfill_urgency_for_voted_bills",
        "estimated_bills": 333,
        "estimated_minutes": 8,
    }


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
