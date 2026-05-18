"""
Pipeline trigger + observability endpoints.

POST /pipeline/run     — queue the nightly orchestrator as a BackgroundTask
GET  /pipeline/status  — latest run per stage, for the /admin/pipeline page
"""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.sync import _verify_secret  # reuse the same gate
from app.db import get_db
from app.pipeline.orchestrator import _STAGES, run_nightly_pipeline

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/run")
async def trigger_nightly_pipeline(
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(_verify_secret)],
):
    """Queue a full pipeline run. Same secret-gate as /sync endpoints in
    production; bypassed when ENVIRONMENT=development."""
    background_tasks.add_task(run_nightly_pipeline)
    return {
        "status":   "queued",
        "pipeline": "nightly",
        "stages":   [name for name, _fn in _STAGES],
    }


# Latest row per stage. DISTINCT ON is the cleanest cross-join-free pattern.
_LATEST_PER_STAGE_SQL = sa_text("""
SELECT DISTINCT ON (stage)
    stage,
    started_at,
    completed_at,
    records_processed,
    status,
    error
FROM pipeline_runs
ORDER BY stage, started_at DESC
""")


@router.get("/status")
async def get_pipeline_status(db: Annotated[AsyncSession, Depends(get_db)]):
    """
    Returns one row per known stage, picking the most recent run. Stages
    that never ran appear with status='never' so the admin page can render
    a full table without scattered missing rows. No auth — pipeline health
    is operational data, not sensitive.
    """
    rows = (await db.execute(_LATEST_PER_STAGE_SQL)).mappings().all()
    by_stage = {r["stage"]: r for r in rows}

    items = []
    for name, _fn in _STAGES:
        r = by_stage.get(name)
        if r is None:
            items.append({
                "stage":             name,
                "status":            "never",
                "started_at":        None,
                "completed_at":      None,
                "duration_seconds":  None,
                "records_processed": 0,
                "error":             None,
            })
            continue
        completed = r["completed_at"]
        started = r["started_at"]
        dur = (
            (completed - started).total_seconds()
            if (completed and started) else None
        )
        items.append({
            "stage":             r["stage"],
            "status":            r["status"],
            "started_at":        started.isoformat() if started else None,
            "completed_at":      completed.isoformat() if completed else None,
            "duration_seconds":  dur,
            "records_processed": r["records_processed"] or 0,
            "error":             r["error"],
        })

    return {"stages": items}
