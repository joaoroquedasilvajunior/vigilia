"""
Sync jobs for Câmara dos Deputados data.

Entry points:
  - sync_legislators()      — upsert all deputies for the current legislature
  - sync_recent_bills()     — upsert bills from the last N days
  - sync_votes_for_bill()   — pull all individual votes for one bill
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.ingestion.camara_client import CamaraClient
from app.models import Bill, Legislator, Party, Session, Vote

logger = logging.getLogger(__name__)


def _parse_date(value):
    """Coerce an API date value to a Python date, or None.

    The Câmara API returns dates as ISO-8601 datetime strings
    (e.g. '2019-04-03T21:31') but the DB columns are DATE type.
    Passing the raw string causes 'str' object has no attribute 'toordinal'.
    """
    if not value:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value).date()
    # Already a date or datetime object
    return value if not hasattr(value, "date") else value.date()


async def _upsert_party_by_acronym(session, acronym: str) -> str | None:
    """Ensure a party row exists; return its UUID."""
    if not acronym:
        return None
    result = await session.execute(select(Party).where(Party.acronym == acronym))
    party = result.scalar_one_or_none()
    if not party:
        party = Party(acronym=acronym)
        session.add(party)
        await session.flush()
    return party.id


async def sync_legislators() -> None:
    """Upsert all deputies for the current legislature (57th)."""
    logger.info("sync_legislators: starting")
    count = 0

    async with CamaraClient() as client:
        async with AsyncSessionLocal() as db:
            async for leg_data in client.get_legislators():
                try:
                    detail = await client.get_legislator_detail(leg_data["camara_id"])
                    leg_data.update(detail)

                    party_id = await _upsert_party_by_acronym(db, leg_data.pop("party_acronym", None))

                    stmt = pg_insert(Legislator).values(
                        camara_id=leg_data["camara_id"],
                        name=leg_data["name"],
                        display_name=leg_data.get("display_name"),
                        chamber="camara",
                        state_uf=leg_data.get("state_uf", ""),
                        nominal_party_id=party_id,
                        photo_url=leg_data.get("photo_url"),
                        education_level=leg_data.get("education_level"),
                        cpf_hash=leg_data.get("cpf_hash"),
                        updated_at=datetime.now(),
                    ).on_conflict_do_update(
                        index_elements=["camara_id"],
                        set_={
                            "name": leg_data["name"],
                            "display_name": leg_data.get("display_name"),
                            "nominal_party_id": party_id,
                            "photo_url": leg_data.get("photo_url"),
                            "education_level": leg_data.get("education_level"),
                            "updated_at": datetime.now(),
                        },
                    )
                    await db.execute(stmt)
                    count += 1

                    if count % 50 == 0:
                        await db.commit()
                        logger.info("sync_legislators: %d upserted", count)

                except Exception as exc:
                    logger.warning("sync_legislators: failed for %s — %s", leg_data.get("camara_id"), exc)

            await db.commit()

    logger.info("sync_legislators: done, %d total", count)


async def sync_recent_bills(days_back: int = 7) -> None:
    """Upsert bills presented in the last `days_back` days."""
    since = datetime.now() - timedelta(days=days_back)
    logger.info("sync_recent_bills: since %s", since.date())
    count = 0

    async with CamaraClient() as client:
        async with AsyncSessionLocal() as db:
            async for bill_data in client.get_bills(since_date=since):
                try:
                    if not bill_data.get("number") or not bill_data.get("year"):
                        continue

                    stmt = pg_insert(Bill).values(
                        camara_id=bill_data["camara_id"],
                        type=bill_data.get("type"),
                        number=bill_data["number"],
                        year=bill_data["year"],
                        title=bill_data["title"] or "",
                        summary_official=bill_data.get("summary_official"),
                        status=bill_data.get("status"),
                        urgency_regime=bill_data.get("urgency_regime", False),
                        presentation_date=_parse_date(bill_data.get("presentation_date")),
                        final_vote_date=_parse_date(bill_data.get("final_vote_date")),
                        updated_at=datetime.now(),
                    ).on_conflict_do_update(
                        index_elements=["camara_id"],
                        set_={
                            "status": bill_data.get("status"),
                            "title": bill_data["title"] or "",
                            "updated_at": datetime.now(),
                        },
                    )
                    await db.execute(stmt)
                    count += 1

                    if count % 100 == 0:
                        await db.commit()
                        logger.info("sync_recent_bills: %d upserted", count)

                except Exception as exc:
                    logger.warning("sync_recent_bills: failed for %s — %s", bill_data.get("camara_id"), exc)

            await db.commit()

    logger.info("sync_recent_bills: done, %d total", count)


async def _fetch_and_upsert_bill(client: "CamaraClient", db: "AsyncSession", camara_id: int) -> None:
    """Fetch a single bill by camara_id from the API and upsert it into the DB."""
    data = await client._get(f"/proposicoes/{camara_id}")
    raw = data.get("dados", {})
    if not raw:
        raise ValueError(f"Câmara API returned no data for proposicao camara_id={camara_id}")
    bill_data = client._normalize_bill(raw)
    if not bill_data.get("number") or not bill_data.get("year"):
        raise ValueError(f"Incomplete bill data for camara_id={camara_id}: {bill_data}")
    stmt = pg_insert(Bill).values(
        camara_id=bill_data["camara_id"],
        type=bill_data.get("type"),
        number=bill_data["number"],
        year=bill_data["year"],
        title=bill_data["title"] or "",
        summary_official=bill_data.get("summary_official"),
        status=bill_data.get("status"),
        urgency_regime=bill_data.get("urgency_regime", False),
        presentation_date=_parse_date(bill_data.get("presentation_date")),
        final_vote_date=_parse_date(bill_data.get("final_vote_date")),
        updated_at=datetime.now(),
    ).on_conflict_do_update(
        index_elements=["camara_id"],
        set_={
            "status": bill_data.get("status"),
            "title": bill_data["title"] or "",
            "updated_at": datetime.now(),
        },
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("_fetch_and_upsert_bill: upserted camara_id=%d (%s %s/%s)",
                camara_id, bill_data.get("type"), bill_data.get("number"), bill_data.get("year"))


async def sync_votes_for_bill(bill_camara_id: int) -> None:
    """
    Pull all individual votes for a bill and store them.
    Designed to be called after a bill's status transitions to 'votação'.
    If the bill isn't in the DB yet, fetches it from the Câmara API first.
    """
    logger.info("sync_votes_for_bill: bill camara_id=%d", bill_camara_id)

    async with CamaraClient() as client:
        async with AsyncSessionLocal() as db:
            bill_result = await db.execute(select(Bill).where(Bill.camara_id == bill_camara_id))
            bill = bill_result.scalar_one_or_none()
            if not bill:
                logger.info("sync_votes_for_bill: bill not in DB, fetching from API first")
                await _fetch_and_upsert_bill(client, db, bill_camara_id)
                bill_result = await db.execute(select(Bill).where(Bill.camara_id == bill_camara_id))
                bill = bill_result.scalar_one_or_none()
            if not bill:
                raise ValueError(f"Bill camara_id={bill_camara_id} could not be fetched from API")

            raw_votes = await client.get_votes_for_bill(bill_camara_id)

            for v in raw_votes:
                if not v.get("legislator_camara_id"):
                    continue

                leg_result = await db.execute(
                    select(Legislator).where(Legislator.camara_id == v["legislator_camara_id"])
                )
                legislator = leg_result.scalar_one_or_none()
                if not legislator:
                    logger.debug("Legislator camara_id=%s not found, skipping", v["legislator_camara_id"])
                    continue

                # Resolve session row if we have the camara session id
                session_id = None
                if v.get("session_camara_id"):
                    sess_result = await db.execute(
                        select(Session).where(Session.camara_id == v["session_camara_id"])
                    )
                    sess = sess_result.scalar_one_or_none()
                    if not sess:
                        sess = Session(camara_id=v["session_camara_id"], session_date=datetime.now().date())
                        db.add(sess)
                        await db.flush()
                    session_id = sess.id

                followed = None
                if v.get("party_orientation") not in ("livre", None):
                    followed = v["vote_value"] == v["party_orientation"]

                stmt = pg_insert(Vote).values(
                    legislator_id=legislator.id,
                    bill_id=bill.id,
                    session_id=session_id,
                    vote_value=v["vote_value"],
                    party_orientation=v.get("party_orientation"),
                    voted_at=v.get("voted_at"),
                    followed_party_line=followed,
                ).on_conflict_do_update(
                    index_elements=["legislator_id", "bill_id"],
                    set_={
                        "vote_value": v["vote_value"],
                        "party_orientation": v.get("party_orientation"),
                        "voted_at": v.get("voted_at"),
                        "followed_party_line": followed,
                    },
                )
                await db.execute(stmt)

            await db.commit()

    logger.info("sync_votes_for_bill: done for bill camara_id=%d", bill_camara_id)


# ── High-profile bills ────────────────────────────────────────────────────────
# Curated list of camara_ids for bills worth pre-loading vote data for.
# These are pulled on the next scheduled sync so the votes table is populated
# even before the full nightly vote-scan is implemented.
HIGH_PROFILE_BILL_CAMARA_IDS: list[int] = [
    2196833,  # PEC 45/2019  — Reforma Tributária
    2192459,  # PEC  6/2019  — Reforma da Previdência
    2256735,  # PL 2630/2020 — Lei das Fake News
    345311,   # PL  490/2007 — Marco Temporal Indígena
    257161,   # PL 2159/2021 — Licenciamento Ambiental
    46249,    # PL 6299/2002 — Agrotóxicos
    2209381,  # PL 3723/2019 — Flexibilização porte de armas
    2262083,  # PEC 32/2020  — Reforma Administrativa
    2233802,  # PEC 221/2019 — Escala 6x1 / Redução da jornada de trabalho
]


async def sync_high_profile_bills_votes() -> None:
    """
    Pull votes for every bill in HIGH_PROFILE_BILL_CAMARA_IDS.

    If a bill isn't in the DB yet (e.g. its batch hasn't been ingested),
    sync_votes_for_bill will fetch and upsert it from the Câmara API first.
    """
    logger.info("sync_high_profile_bills_votes: %d bills", len(HIGH_PROFILE_BILL_CAMARA_IDS))
    for camara_id in HIGH_PROFILE_BILL_CAMARA_IDS:
        try:
            await sync_votes_for_bill(camara_id)
        except Exception as exc:
            logger.error("sync_high_profile_bills_votes: failed for camara_id=%d — %s", camara_id, exc)


if __name__ == "__main__":
    async def _main() -> None:
        logging.basicConfig(level=logging.INFO)
        print("Starting daily sync...")
        await sync_legislators()
        await sync_recent_bills(days_back=2)
        await sync_high_profile_bills_votes()
        print("Sync complete.")

    asyncio.run(_main())
