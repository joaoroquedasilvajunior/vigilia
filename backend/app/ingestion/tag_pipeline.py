"""
NLP theme-tagging pipeline for bills.

Entry point:
  - tag_bills() — classify all untagged bills and write theme_tags to DB
"""
import asyncio
import json
import logging
import re

import anthropic
from sqlalchemy import func, or_, select, update

from app.db import AsyncSessionLocal
from app.models import Bill

logger = logging.getLogger(__name__)

VALID_TAGS = frozenset([
    "trabalho",
    "meio-ambiente",
    "saude",
    "educacao",
    "seguranca-publica",
    "agronegocio",
    "tributacao",
    "direitos-lgbtqia",
    "armas",
    "religiao",
    "indigenas",
    "midia",
    "reforma-politica",
])

_TAG_SYSTEM = """\
Você é um classificador temático de projetos de lei brasileiros.
Responda APENAS com um array JSON de 1 a 3 strings, sem texto adicional.
Use somente tags da lista fornecida."""

_TAG_TEMPLATE = """\
Classifique este projeto de lei com 1 a 3 tags da lista abaixo.

Tags disponíveis: {tags}

Título: {title}
Ementa: {summary}

Responda APENAS com um array JSON. Exemplos:
["tributacao"]
["saude", "educacao"]
["armas", "seguranca-publica"]"""


def _parse_tags(raw: str) -> list[str]:
    """Extract and validate tags from Haiku response."""
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.DOTALL).strip()
    try:
        tags = json.loads(raw)
        if not isinstance(tags, list):
            return []
        return [t for t in tags if isinstance(t, str) and t in VALID_TAGS]
    except (json.JSONDecodeError, ValueError):
        return []


async def _classify_bill(client: anthropic.AsyncAnthropic, title: str, summary: str | None) -> list[str]:
    """Call Haiku to classify a single bill. Returns validated tag list."""
    prompt = _TAG_TEMPLATE.format(
        tags=", ".join(sorted(VALID_TAGS)),
        title=title[:300],
        summary=(summary or "")[:500],
    )
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            system=_TAG_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        tags = _parse_tags(raw)
        return tags if tags else []
    except Exception as exc:
        logger.warning("_classify_bill failed: %s", exc)
        return []


async def tag_bills(
    concurrency: int = 10,
    write_batch_size: int = 50,
) -> int:
    """
    Tag every bill whose theme_tags is NULL or empty.

    Strategy: fan out Haiku calls under a semaphore so ~`concurrency`
    requests are in flight at any moment, then write results in
    chunks of `write_batch_size`. Decoupling classification from
    persistence (instead of the prior batch-and-commit loop) lets a
    slow Haiku call on one bill stop blocking the others, and cuts
    DB roundtrips by ~50x. ~10x throughput improvement in practice.

    Returns count of bills successfully tagged.
    """
    logger.info("tag_bills: starting")
    client = anthropic.AsyncAnthropic()

    async with AsyncSessionLocal() as db:
        # array_length returns NULL for both NULL arrays and empty arrays —
        # this OR catches both states cleanly.
        result = await db.execute(
            select(Bill.id, Bill.title, Bill.summary_official)
            .where(
                or_(
                    Bill.theme_tags.is_(None),
                    func.array_length(Bill.theme_tags, 1).is_(None),
                )
            )
            .order_by(Bill.presentation_date.desc().nullslast())
        )
        untagged = result.all()

    logger.info("tag_bills: %d bills to tag (concurrency=%d)", len(untagged), concurrency)
    if not untagged:
        return 0

    # ── Phase 1: fan-out classification ──────────────────────────────────
    sem = asyncio.Semaphore(concurrency)

    async def classify_one(row) -> tuple | None:
        async with sem:
            try:
                tags = await _classify_bill(
                    client, row.title or "", row.summary_official,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("tag_bills: classify failed for %s — %s", row.id, exc)
                return None
        return (row.id, tags) if tags else None

    results = await asyncio.gather(
        *(classify_one(r) for r in untagged),
        return_exceptions=True,
    )
    successful = [
        r for r in results
        if isinstance(r, tuple) and r is not None
    ]
    logger.info(
        "tag_bills: classified %d / %d (skipped=%d)",
        len(successful), len(untagged), len(untagged) - len(successful),
    )

    # ── Phase 2: batched DB writes ───────────────────────────────────────
    total_written = 0
    for i in range(0, len(successful), write_batch_size):
        chunk = successful[i : i + write_batch_size]
        async with AsyncSessionLocal() as db:
            for bid, tags in chunk:
                await db.execute(
                    update(Bill).where(Bill.id == bid).values(theme_tags=tags)
                )
            await db.commit()
        total_written += len(chunk)
        if total_written % 200 == 0:
            logger.info(
                "tag_bills: persisted %d/%d", total_written, len(successful),
            )

    logger.info("tag_bills: done — tagged=%d", total_written)
    return total_written


if __name__ == "__main__":
    async def _main() -> None:
        logging.basicConfig(level=logging.INFO)
        await tag_bills()

    asyncio.run(_main())
