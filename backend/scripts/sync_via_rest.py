"""
REST-API sync for environments where direct asyncpg DB access is unavailable
(e.g. IPv6-only Supabase projects on IPv4-only networks).

Uses PostgREST upsert endpoints — identical logic to sync_pipeline.py
but communicates via HTTPS instead of direct Postgres.

Requires SUPABASE_SERVICE_ROLE_KEY (sb_secret_...) in .env — the anon
(sb_publishable_...) key cannot bypass RLS for writes.

Usage:
  python scripts/sync_via_rest.py legislators   # sync all deputies
  python scripts/sync_via_rest.py bills         # sync last 90 days
  python scripts/sync_via_rest.py both          # legislators then bills
"""
import asyncio
import logging
import sys
from datetime import datetime, timedelta
from typing import Any

import httpx
from dotenv import dotenv_values

from app.ingestion.camara_client import CamaraClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

cfg = dotenv_values(".env")
SUPABASE_URL = cfg["SUPABASE_URL"].rstrip("/")
SERVICE_ROLE_KEY = cfg.get("SUPABASE_SERVICE_ROLE_KEY", "")

if not SERVICE_ROLE_KEY.startswith(("eyJ", "sb_secret_")):
    print(
        "\n⚠️  SUPABASE_SERVICE_ROLE_KEY looks like an anon/publishable key.\n"
        "   Go to Supabase → Settings → API → service_role key\n"
        "   It should start with 'sb_secret_...' or 'eyJ...'\n"
    )
    sys.exit(1)

HEADERS = {
    "apikey": SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}


async def rest_upsert(client: httpx.AsyncClient, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    resp = await client.post(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=HEADERS,
        json=rows,
        timeout=30,
    )
    if resp.status_code not in (200, 201, 204):
        logger.error("upsert %s HTTP %d: %s", table, resp.status_code, resp.text[:200])
        resp.raise_for_status()
    return len(rows)


async def rest_get(client: httpx.AsyncClient, table: str, filters: str = "") -> list[dict]:
    url = f"{SUPABASE_URL}/rest/v1/{table}{filters}"
    resp = await client.get(url, headers={**HEADERS, "Prefer": ""}, timeout=15)
    resp.raise_for_status()
    return resp.json()


async def ensure_party(client: httpx.AsyncClient, acronym: str) -> str | None:
    if not acronym:
        return None
    rows = await rest_get(client, "parties", f"?acronym=eq.{acronym}&select=id")
    if rows:
        return rows[0]["id"]
    new_rows = await client.post(
        f"{SUPABASE_URL}/rest/v1/parties",
        headers={**HEADERS, "Prefer": "return=representation"},
        json=[{"acronym": acronym}],
        timeout=10,
    )
    new_rows.raise_for_status()
    return new_rows.json()[0]["id"]


async def sync_legislators(http: httpx.AsyncClient) -> None:
    logger.info("sync_legislators: starting")
    total = 0

    async with CamaraClient() as client:
        async for leg_data in client.get_legislators():
            try:
                detail = await client.get_legislator_detail(leg_data["camara_id"])
                leg_data.update(detail)

                party_id = await ensure_party(http, leg_data.pop("party_acronym", None))

                row: dict[str, Any] = {
                    "camara_id": leg_data["camara_id"],
                    "name": leg_data["name"],
                    "display_name": leg_data.get("display_name"),
                    "chamber": "camara",
                    "state_uf": leg_data.get("state_uf") or "",
                    "nominal_party_id": party_id,
                    "photo_url": leg_data.get("photo_url"),
                    "education_level": leg_data.get("education_level"),
                    "cpf_hash": leg_data.get("cpf_hash"),
                    "updated_at": datetime.now().isoformat(),
                }
                # Remove None values so Supabase doesn't overwrite with null
                row = {k: v for k, v in row.items() if v is not None}

                await rest_upsert(http, "legislators", [row])
                total += 1

                if total % 50 == 0:
                    logger.info("sync_legislators: %d upserted", total)

            except Exception as exc:
                logger.warning(
                    "sync_legislators: failed for %s — %s", leg_data.get("camara_id"), exc
                )

    logger.info("sync_legislators: done, %d total", total)


async def sync_recent_bills(http: httpx.AsyncClient, days_back: int = 90) -> None:
    since = datetime.now() - timedelta(days=days_back)
    logger.info("sync_recent_bills: since %s", since.date())
    total = 0
    batch: list[dict] = []

    async with CamaraClient() as client:
        async for bill_data in client.get_bills(since_date=since):
            try:
                if not bill_data.get("number") or not bill_data.get("year"):
                    continue

                row: dict[str, Any] = {
                    "camara_id": bill_data["camara_id"],
                    "type": bill_data.get("type"),
                    "number": bill_data["number"],
                    "year": bill_data["year"],
                    "title": bill_data.get("title") or "",
                    "summary_official": bill_data.get("summary_official"),
                    "status": bill_data.get("status"),
                    "urgency_regime": bill_data.get("urgency_regime", False),
                    "presentation_date": bill_data.get("presentation_date"),
                    "updated_at": datetime.now().isoformat(),
                }
                row = {k: v for k, v in row.items() if v is not None}
                batch.append(row)

                if len(batch) >= 50:
                    await rest_upsert(http, "bills", batch)
                    total += len(batch)
                    logger.info("sync_recent_bills: %d upserted", total)
                    batch = []

            except Exception as exc:
                logger.warning(
                    "sync_recent_bills: failed for %s — %s", bill_data.get("camara_id"), exc
                )

    if batch:
        await rest_upsert(http, "bills", batch)
        total += len(batch)

    logger.info("sync_recent_bills: done, %d total", total)


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"

    async with httpx.AsyncClient() as http:
        if mode in ("legislators", "both"):
            await sync_legislators(http)
        if mode in ("bills", "both"):
            await sync_recent_bills(http)

    logger.info("Sync complete.")


if __name__ == "__main__":
    asyncio.run(main())
