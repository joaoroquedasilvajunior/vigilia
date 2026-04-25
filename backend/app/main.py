import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes import bills, farol, legislators, sync
from app.core.config import settings

logging.basicConfig(level=settings.log_level)

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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
