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

from sqlalchemy import delete as sa_delete, select
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


async def sync_votes_for_bill_principal(bill_camara_id: int) -> dict:
    """
    Re-sync votes for a bill using ONLY its principal voting session
    (texto-base / redação final / turno único). Wipes any pre-existing
    votes for the bill first so stale destaque-derived rows can't
    survive re-ingestion.

    Returns a small dict describing what happened, suitable for logging
    or batch-result aggregation.
    """
    logger.info("sync_votes_for_bill_principal: bill camara_id=%d", bill_camara_id)

    async with CamaraClient() as client:
        async with AsyncSessionLocal() as db:
            bill_result = await db.execute(
                select(Bill).where(Bill.camara_id == bill_camara_id)
            )
            bill = bill_result.scalar_one_or_none()
            if not bill:
                await _fetch_and_upsert_bill(client, db, bill_camara_id)
                bill_result = await db.execute(
                    select(Bill).where(Bill.camara_id == bill_camara_id)
                )
                bill = bill_result.scalar_one_or_none()
            if not bill:
                raise ValueError(
                    f"Bill camara_id={bill_camara_id} could not be fetched from API"
                )

            votes, meta = await client.get_principal_votes_for_bill(bill_camara_id)

            # Clear stale votes (very likely from destaque sessions) before
            # repopulating from the principal session only.
            deleted = (await db.execute(
                sa_delete(Vote).where(Vote.bill_id == bill.id)
            )).rowcount or 0

            inserted = 0
            for v in votes:
                if not v.get("legislator_camara_id"):
                    continue
                leg_result = await db.execute(
                    select(Legislator).where(
                        Legislator.camara_id == v["legislator_camara_id"]
                    )
                )
                legislator = leg_result.scalar_one_or_none()
                if not legislator:
                    continue

                session_id = None
                if v.get("session_camara_id"):
                    sess_result = await db.execute(
                        select(Session).where(
                            Session.camara_id == v["session_camara_id"]
                        )
                    )
                    sess = sess_result.scalar_one_or_none()
                    if not sess:
                        sess = Session(
                            camara_id=v["session_camara_id"],
                            session_date=datetime.now().date(),
                        )
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
                inserted += 1

            await db.commit()

    result = {
        "camara_id": bill_camara_id,
        "deleted": deleted,
        "inserted": inserted,
        **meta,
    }
    logger.info("sync_votes_for_bill_principal: %s", result)
    return result


async def sync_votes_principal_for_bills(camara_ids: list[int]) -> list[dict]:
    """Run sync_votes_for_bill_principal sequentially over a list of bills.

    Sequential (not gathered) to be polite to the Câmara API and to make
    failures easier to attribute. Per-bill failures don't abort the batch.
    """
    results: list[dict] = []
    for cid in camara_ids:
        try:
            results.append(await sync_votes_for_bill_principal(cid))
        except Exception as exc:  # noqa: BLE001
            logger.exception("sync_votes_for_bill_principal failed for %s", cid)
            results.append({"camara_id": cid, "error": str(exc)})
    return results


# ── High-profile bills ────────────────────────────────────────────────────────
# Curated list of camara_ids for bills worth pre-loading vote data for.
# These are pulled on the next scheduled sync so the votes table is populated
# even before the full nightly vote-scan is implemented.
HIGH_PROFILE_BILL_CAMARA_IDS: list[int] = [
    2196833,  # PEC 45/2019   — Reforma Tributária
    2192459,  # PEC  6/2019   — Reforma da Previdência
    2256735,  # PL 2630/2020  — Lei das Fake News
    345311,   # PL  490/2007  — Marco Temporal Indígena
    257161,   # PL 2159/2021  — Licenciamento Ambiental (Transformado em Norma 2025)
    46249,    # PL 6299/2002  — Agrotóxicos
    2209381,  # PL 3723/2019  — Flexibilização porte de armas
    2262083,  # PEC 32/2020   — Reforma Administrativa
    2233802,  # PEC 221/2019  — Escala 6x1 / Redução da jornada de trabalho
    2487436,  # PL 1087/2025  → Lei 15.270/2025 — Reforma do IR
    2358548,  # PL 2162/2023  — Anistia 8 de Janeiro
    2270800,  # PEC  3/2021   — PEC da Blindagem (imunidade parlamentar)
    2374540,  # PL 3640/2023  — Limita decisões monocráticas STF
    2430143,  # PLP 68/2024   — Regulamentação reforma tributária IBS/CBS
    2352476,  # PEC  9/2023   — Anistia partidos / cotas raciais
    2434493,  # PL 1904/2024  — Equiparação aborto após 22 semanas
]


async def fetch_voted_bill_ids(
    date_start: str = "2023-02-01",
    date_end: str | None = None,
    plenary_only: bool = True,
) -> list[int]:
    """
    Walk the Câmara /votacoes endpoint between date_start and date_end and
    return a deduplicated list of bill camara_ids that actually had at least
    one voting session in that window.

    Filters to PLEN (plenary) by default since committee votes have <40
    voters and would skew clustering. The session id format is
    "{bill_camara_id}-{seq}" so we extract the bill id from there
    (the API's proposicaoObjeto / uriProposicaoObjeto fields are often null).
    """
    if date_end is None:
        date_end = datetime.now().strftime("%Y-%m-%d")

    logger.info(
        "fetch_voted_bill_ids: %s → %s (plenary_only=%s)",
        date_start, date_end, plenary_only,
    )

    seen: set[int] = set()
    sessions = 0
    async with CamaraClient() as client:
        async for session in client.get_voting_sessions(
            date_start=date_start, date_end=date_end, plenary_only=plenary_only
        ):
            sessions += 1
            seen.add(session["bill_camara_id"])

    bill_ids = sorted(seen)
    logger.info(
        "fetch_voted_bill_ids: %d unique bills (across %d sessions)",
        len(bill_ids), sessions,
    )
    return bill_ids


async def _bill_has_votes(db, camara_id: int) -> bool:
    """Skip-check: does this bill already have any vote rows?"""
    row = await db.execute(
        select(Vote.id)
        .join(Bill, Vote.bill_id == Bill.id)
        .where(Bill.camara_id == camara_id)
        .limit(1)
    )
    return row.scalar_one_or_none() is not None


async def sync_all_voted_bills(
    date_start: str = "2023-02-01",
    date_end: str | None = None,
    delay_between_bills: float = 1.0,
    skip_already_synced: bool = True,
) -> None:
    """
    Full coverage vote sync for every bill that had a plenary vote
    between date_start and date_end (defaults: 2023-02-01 to today).

    Algorithm:
      1. List unique bill camara_ids from /votacoes
      2. For each bill: skip if it already has votes; otherwise call
         sync_votes_for_bill (which auto-fetches the bill if missing)
      3. Sleep `delay_between_bills` seconds between bills to be polite
      4. Log progress every 10 bills

    Idempotent: skip-if-has-votes makes restarts safe — the job resumes
    where it left off after a crash.

    Realistic runtime: 50-200+ bills × 30s-5min each = several hours.
    Multi-session bills (e.g. PEC turn votes) take longer.
    """
    bill_ids = await fetch_voted_bill_ids(date_start=date_start, date_end=date_end)
    if not bill_ids:
        logger.warning("sync_all_voted_bills: no voted bills found in window")
        return

    total = len(bill_ids)
    skipped = synced = failed = 0
    start_ts = datetime.now()

    for i, camara_id in enumerate(bill_ids, start=1):
        try:
            if skip_already_synced:
                async with AsyncSessionLocal() as db:
                    if await _bill_has_votes(db, camara_id):
                        skipped += 1
                        continue

            await sync_votes_for_bill(camara_id)
            synced += 1
        except Exception as exc:
            failed += 1
            logger.warning(
                "sync_all_voted_bills: bill %d failed — %s", camara_id, exc,
            )

        if i % 10 == 0 or i == total:
            elapsed = (datetime.now() - start_ts).total_seconds()
            rate = i / max(elapsed, 1.0)
            eta_min = (total - i) / max(rate, 0.001) / 60
            logger.info(
                "sync_all_voted_bills: %d/%d processed "
                "(synced=%d skipped=%d failed=%d) — rate %.2f/s, ETA %.0f min",
                i, total, synced, skipped, failed, rate, eta_min,
            )

        await asyncio.sleep(delay_between_bills)

    logger.info(
        "sync_all_voted_bills: COMPLETE — total=%d synced=%d skipped=%d failed=%d",
        total, synced, skipped, failed,
    )


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
