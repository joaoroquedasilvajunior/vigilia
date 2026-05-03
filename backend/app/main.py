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
_STARTUP_MIGRATIONS = [
    # bills.last_vote_at — denormalized MAX(voted_at) per bill, used by the
    # /political-temperature dashboard. bills.updated_at is touched on every
    # nightly sync and so can't be used to detect "recently active" bills.
    """ALTER TABLE bills ADD COLUMN IF NOT EXISTS last_vote_at TIMESTAMP""",
    # Backfill rows that haven't been populated yet. WHERE … IS NULL keeps
    # this idempotent: re-deploys touch nothing once every bill has a value.
    """
    UPDATE bills b
    SET last_vote_at = (
        SELECT MAX(v.voted_at) FROM votes v WHERE v.bill_id = b.id
    )
    WHERE b.last_vote_at IS NULL
    """,
]


async def _run_startup_migrations() -> None:
    async with AsyncSessionLocal() as db:
        for sql in _STARTUP_MIGRATIONS:
            try:
                await db.execute(text(sql))
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("startup migration skipped (%s): %s", sql.split()[0], exc)
                await db.rollback()

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
    await _run_startup_migrations()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
