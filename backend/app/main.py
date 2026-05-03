import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.routes import analysis, bills, clusters, farol, legislators, stats, sync
from app.core.config import settings
from app.db import AsyncSessionLocal

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


# ── Lightweight startup migrations ────────────────────────────────────────────
# We don't use Alembic in this project (Supabase manages base schema). Small
# additive changes — new nullable columns, backfills — go here as idempotent
# SQL that runs once on startup. Failures are logged but never crash the
# boot, so a transient Supabase hiccup doesn't take the API down.
# Fast DDL runs synchronously at startup — must complete in << 30s
# (Railway's healthcheck window). Heavy data-touching migrations are
# deferred to a background task so they don't block /health.
_FAST_STARTUP_DDL = [
    # bills.last_vote_at — denormalized MAX(voted_at) per bill, used by
    # the /political-temperature dashboard. bills.updated_at is touched
    # on every nightly metadata sync and can't serve as a "recent" signal.
    "ALTER TABLE bills ADD COLUMN IF NOT EXISTS last_vote_at TIMESTAMP",
]

_BACKGROUND_BACKFILL_SQL = """
UPDATE bills b
SET last_vote_at = (
    SELECT MAX(v.voted_at) FROM votes v WHERE v.bill_id = b.id
)
WHERE b.last_vote_at IS NULL
"""


async def _run_fast_startup_ddl() -> None:
    async with AsyncSessionLocal() as db:
        for sql in _FAST_STARTUP_DDL:
            try:
                await db.execute(text(sql))
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "startup DDL skipped (%s): %s", sql.split()[0], exc,
                )
                await db.rollback()


async def _background_last_vote_at_backfill() -> None:
    """
    Heavy UPDATE that previously ran at startup and bounced Railway's
    healthcheck (Supabase round-trip × 27k rows > 30s). Now spawned as a
    fire-and-forget task AFTER the server is accepting traffic.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(text(_BACKGROUND_BACKFILL_SQL))
            await db.commit()
            logger.info(
                "background backfill: bills.last_vote_at touched %d rows",
                result.rowcount or 0,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("background last_vote_at backfill failed: %s", exc)

app = FastAPI(
    title="Vigília API",
    description="Brazilian Legislative Monitoring Platform",
    version="0.1.0",
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://vigilia.com.br",
        "https://frontend-bice-two-19.vercel.app",
        "https://plataforma-vigilia.vercel.app",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(legislators.router, prefix="/api/v1")
app.include_router(bills.router, prefix="/api/v1")
app.include_router(farol.router, prefix="/api/v1")
app.include_router(sync.router, prefix="/api/v1")
app.include_router(clusters.router, prefix="/api/v1")
app.include_router(stats.router, prefix="/api/v1")
app.include_router(analysis.router, prefix="/api/v1")


@app.on_event("startup")
async def _startup() -> None:
    # 1) Fast DDL synchronously so every other endpoint can rely on the
    #    column existing (~hundreds of ms even over the Atlantic).
    await _run_fast_startup_ddl()
    # 2) Heavy backfill spawned and detached. asyncio.create_task lets
    #    the startup hook return immediately so /health responds in time.
    asyncio.create_task(_background_last_vote_at_backfill())


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
