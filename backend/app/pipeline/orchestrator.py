"""
Master pipeline orchestrator. Runs the seven stages sequentially with
per-stage timing + pipeline_runs logging. A failed stage logs and continues
— we never want a single transient Câmara error to take the whole nightly
update down.

Entry points:
  - run_nightly_pipeline(): the async function, callable from FastAPI
  - python -m app.pipeline.orchestrator: CLI wrapper for Railway cron
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Awaitable, Callable

from sqlalchemy import text as sa_text

from app.db import AsyncSessionLocal
from app.pipeline.stages import (
    compute_alignment_for_active_deputies,
    compute_clusters_if_needed,
    compute_discipline_for_active_deputies,
    run_constitutional_scoring_incremental,
    run_tag_pipeline_incremental,
    sync_new_plenary_votes,
    sync_orientations_for_recent_sessions,
)

logger = logging.getLogger(__name__)


# Stage = (db-friendly name, async function returning int "records processed")
StageFn = Callable[[], Awaitable[int]]
_STAGES: list[tuple[str, StageFn]] = [
    ("ingest_votes",         sync_new_plenary_votes),
    ("sync_orientations",    sync_orientations_for_recent_sessions),
    ("tag_bills",            run_tag_pipeline_incremental),
    ("score_constitutional", run_constitutional_scoring_incremental),
    ("compute_discipline",   compute_discipline_for_active_deputies),
    ("compute_alignment",    compute_alignment_for_active_deputies),
    ("compute_clusters",     compute_clusters_if_needed),
]


async def _log_run(
    stage: str,
    started: datetime,
    completed: datetime,
    records: int,
    status: str,
    error: str | None = None,
) -> None:
    """Insert one row into pipeline_runs. Failure to log is logged but
    never propagated — observability shouldn't break the pipeline."""
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                sa_text(
                    "INSERT INTO pipeline_runs "
                    "(id, stage, started_at, completed_at, records_processed, status, error) "
                    "VALUES (:id, :stage, :started, :completed, :records, :status, :error)"
                ),
                {
                    "id":        uuid.uuid4(),
                    "stage":     stage,
                    "started":   started,
                    "completed": completed,
                    "records":   records,
                    "status":    status,
                    "error":     (error or "")[:500] or None,
                },
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("_log_run(%s) failed to persist: %s", stage, exc)


async def run_nightly_pipeline() -> dict:
    """
    Run all seven stages sequentially. Returns a summary dict suitable
    for logging or echoing back to a status endpoint.
    """
    pipeline_started = datetime.now()
    logger.info("run_nightly_pipeline: starting (%d stages)", len(_STAGES))

    results: list[dict] = []
    for stage_name, stage_fn in _STAGES:
        started = datetime.now()
        records = 0
        status = "success"
        error: str | None = None
        try:
            records = int(await stage_fn() or 0)
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("pipeline stage %s failed", stage_name)
        completed = datetime.now()
        duration = (completed - started).total_seconds()
        logger.info(
            "stage %s: %s, records=%d, duration=%.1fs",
            stage_name, status, records, duration,
        )
        await _log_run(stage_name, started, completed, records, status, error)
        results.append({
            "stage":             stage_name,
            "status":            status,
            "records_processed": records,
            "duration_seconds":  duration,
            "error":             error,
        })

    return {
        "started_at":   pipeline_started.isoformat(),
        "completed_at": datetime.now().isoformat(),
        "stages":       results,
    }


def main() -> None:
    """CLI entry point — Railway cron invokes this via
    `python -m app.pipeline.orchestrator`."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = asyncio.run(run_nightly_pipeline())
    # Log the summary one last time at INFO so cron logs have a single
    # grep-friendly line to chart pipeline outcomes against.
    n_ok = sum(1 for s in result["stages"] if s["status"] == "success")
    logger.info(
        "run_nightly_pipeline: done — %d/%d stages succeeded",
        n_ok, len(result["stages"]),
    )


if __name__ == "__main__":
    main()
