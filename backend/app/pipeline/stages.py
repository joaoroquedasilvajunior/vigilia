"""
Thin incremental wrappers around the existing sync/analysis functions.
Each stage function is the unit of work the orchestrator runs and logs;
keeping these tiny makes failure isolation, retries, and audit trivial.

Pattern: a stage function takes no arguments, does its incremental work,
and returns an integer count of records processed (so pipeline_runs can
display "234 new votes" / "8 scored" / etc. in the admin status table).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, text as sa_text

from app.db import AsyncSessionLocal
from app.ingestion.camara_client import CamaraClient
from app.ingestion.sync_pipeline import (
    _fetch_and_upsert_bill,
    sync_votes_for_bill_principal,
)
from app.ingestion.orientation_pipeline import sync_party_orientations
from app.ingestion.tag_pipeline import tag_bills
from app.analysis.constitutional_scorer import (
    compute_constitutional_alignment,
    score_voted_bills,
)
from app.analysis.party_discipline import compute_discipline_and_absence
from app.analysis.clustering import compute_clusters
from app.models import Bill

logger = logging.getLogger(__name__)


# ── Stage 1: ingest new plenary votes ────────────────────────────────────────

async def sync_new_plenary_votes(days_back: int = 2) -> int:
    """
    Pull plenary voting sessions from the last `days_back` days, upsert the
    associated bills, and re-sync principal votes for each.

    Returns the count of distinct bills touched.
    """
    today = datetime.now().date()
    start = today - timedelta(days=days_back)
    logger.info("sync_new_plenary_votes: %s → %s", start, today)

    # Collect distinct bill_camara_ids that had a plenary session in window
    bill_ids: set[int] = set()
    async with CamaraClient() as client:
        async for sess in client.get_voting_sessions(
            date_start=start.isoformat(),
            date_end=today.isoformat(),
            plenary_only=True,
        ):
            cid = sess.get("bill_camara_id")
            if cid:
                bill_ids.add(int(cid))

        logger.info("sync_new_plenary_votes: %d distinct bills voted", len(bill_ids))

        # Upsert bill via detail endpoint (where statusProposicao.regime
        # actually lives — list endpoint omits it), then re-sync principal
        # votes. sync_votes_for_bill_principal also updates bills.last_vote_at
        # at end of transaction, so the activity dashboard auto-refreshes.
        for cid in bill_ids:
            try:
                async with AsyncSessionLocal() as db:
                    await _fetch_and_upsert_bill(client, db, cid)
                await sync_votes_for_bill_principal(cid)
            except Exception as exc:  # noqa: BLE001
                logger.warning("sync_new_plenary_votes: %s failed — %s", cid, exc)

    return len(bill_ids)


# ── Stage 2: party orientations for recent sessions ──────────────────────────

async def sync_orientations_for_recent_sessions(days_back: int = 2) -> int:
    """
    Backfill votes.party_orientation for sessions added in the last
    `days_back` days. The underlying function is incremental at the row
    level (only touches votes whose orientation is still NULL for sessions
    it processes), so calling it with the full sweep is safe but slow —
    here we narrow it to recent sessions by checking sessions.created_at.

    Returns count of sessions touched. Falls back to the full sync if the
    incremental path isn't implementable on the existing helper.
    """
    async with AsyncSessionLocal() as db:
        cnt_row = await db.execute(sa_text(
            "SELECT COUNT(*) FROM sessions WHERE created_at > NOW() - INTERVAL :i AND camara_id IS NOT NULL"
        ), {"i": f"{days_back} days"})
        recent = int(cnt_row.scalar() or 0)
    logger.info("sync_orientations_for_recent_sessions: %d recent sessions", recent)

    # The existing helper walks ALL sessions and skips those already-touched
    # idempotently — for now reuse it. A truly-incremental version is a
    # future optimization once session counts grow large enough to matter.
    await sync_party_orientations()
    return recent


# ── Stage 3: tag unclassified bills ─────────────────────────────────────────

async def run_tag_pipeline_incremental() -> int:
    """
    tag_bills() already filters internally to bills where theme_tags is NULL
    or an empty array. Returns the count of bills it tagged in this run.
    """
    # Snapshot the "untagged" count before so we can report delta even
    # though tag_bills doesn't return one.
    async with AsyncSessionLocal() as db:
        before = int((await db.execute(sa_text(
            "SELECT COUNT(*) FROM bills "
            "WHERE theme_tags IS NULL OR array_length(theme_tags, 1) = 0"
        ))).scalar() or 0)

    await tag_bills()

    async with AsyncSessionLocal() as db:
        after = int((await db.execute(sa_text(
            "SELECT COUNT(*) FROM bills "
            "WHERE theme_tags IS NULL OR array_length(theme_tags, 1) = 0"
        ))).scalar() or 0)

    return max(0, before - after)


# ── Stage 4: score unscored voted bills ──────────────────────────────────────

async def run_constitutional_scoring_incremental() -> int:
    """
    score_voted_bills() already filters internally to bills with NULL
    const_risk_score that have at least one vote. Returns the count of
    bills scored in this run.
    """
    async with AsyncSessionLocal() as db:
        before = int((await db.execute(sa_text(
            "SELECT COUNT(*) FROM bills "
            "WHERE const_risk_score IS NULL "
            "  AND id IN (SELECT DISTINCT bill_id FROM votes)"
        ))).scalar() or 0)

    await score_voted_bills()

    async with AsyncSessionLocal() as db:
        after = int((await db.execute(sa_text(
            "SELECT COUNT(*) FROM bills "
            "WHERE const_risk_score IS NULL "
            "  AND id IN (SELECT DISTINCT bill_id FROM votes)"
        ))).scalar() or 0)

    return max(0, before - after)


# ── Stage 5: discipline ──────────────────────────────────────────────────────

async def compute_discipline_for_active_deputies() -> int:
    """
    The existing compute_discipline_and_absence() is pure SQL over the full
    population (~640 deputies) and runs in seconds. Rather than make it
    per-deputy (which would lose the cross-deputy aggregations it needs),
    we just run it whole and report the count of deputies with recent votes
    so callers know how big the "active" pool was this cycle.
    """
    async with AsyncSessionLocal() as db:
        active = int((await db.execute(sa_text(
            "SELECT COUNT(DISTINCT legislator_id) FROM votes "
            "WHERE voted_at > NOW() - INTERVAL '2 days'"
        ))).scalar() or 0)

    await compute_discipline_and_absence()
    return active


# ── Stage 6: constitutional alignment ────────────────────────────────────────

async def compute_alignment_for_active_deputies() -> int:
    """Same pattern as Stage 5 — bulk recompute, return active count."""
    async with AsyncSessionLocal() as db:
        active = int((await db.execute(sa_text(
            "SELECT COUNT(DISTINCT legislator_id) FROM votes "
            "WHERE voted_at > NOW() - INTERVAL '2 days'"
        ))).scalar() or 0)

    n_updated = await compute_constitutional_alignment()
    # Prefer the underlying function's update count if it returned one;
    # else fall back to the active count for the dashboard label.
    return int(n_updated) if isinstance(n_updated, int) else active


# ── Stage 7: clusters (gated, weekly-ish) ────────────────────────────────────

async def compute_clusters_if_needed(min_new_votes: int = 50) -> int:
    """
    Re-run k-means clustering only when there's enough fresh signal to
    move the cluster boundaries. Looks up the last successful clustering
    run from pipeline_runs and counts votes since then; runs if either
    threshold is exceeded OR if there's no prior run on record.

    Returns the number of legislators clustered (or 0 if skipped).
    """
    async with AsyncSessionLocal() as db:
        last = await db.execute(sa_text(
            "SELECT MAX(completed_at) FROM pipeline_runs "
            "WHERE stage = 'compute_clusters' AND status = 'success'"
        ))
        last_run = last.scalar()

        if last_run is None:
            new_votes = None  # treat "never run" as "do it"
        else:
            cnt = await db.execute(sa_text(
                "SELECT COUNT(*) FROM votes WHERE voted_at > :since"
            ), {"since": last_run})
            new_votes = int(cnt.scalar() or 0)

    if new_votes is not None and new_votes < min_new_votes:
        logger.info(
            "compute_clusters_if_needed: skipped — only %d new votes since last run",
            new_votes,
        )
        return 0

    await compute_clusters()

    async with AsyncSessionLocal() as db:
        n = int((await db.execute(sa_text(
            "SELECT COUNT(*) FROM legislators "
            "WHERE behavioral_cluster_id IS NOT NULL"
        ))).scalar() or 0)
    return n
