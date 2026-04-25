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


async def tag_bills(batch_size: int = 20, delay_between_batches: float = 0.5) -> None:
    """
    Tag all bills where theme_tags IS NULL or empty.
    Processes in batches of `batch_size` with a short delay between batches.
    """
    logger.info("tag_bills: starting")
    client = anthropic.AsyncAnthropic()
    total_tagged = 0
    total_skipped = 0

    async with AsyncSessionLocal() as db:
        # Fetch all untagged bill ids + title + summary in one query
        # array_length returns NULL for both NULL arrays and empty arrays
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

    logger.info("tag_bills: %d bills to tag", len(untagged))

    # Process in batches
    for batch_start in range(0, len(untagged), batch_size):
        batch = untagged[batch_start : batch_start + batch_size]

        # Classify all bills in this batch concurrently
        tasks = [
            _classify_bill(client, row.title or "", row.summary_official)
            for row in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Write results back to DB
        async with AsyncSessionLocal() as db:
            for row, tags in zip(batch, results):
                if isinstance(tags, Exception):
                    logger.warning("tag_bills: exception for bill %s — %s", row.id, tags)
                    total_skipped += 1
                    continue
                if not tags:
                    total_skipped += 1
                    continue
                await db.execute(
                    update(Bill)
                    .where(Bill.id == row.id)
                    .values(theme_tags=tags)
                )
                total_tagged += 1
            await db.commit()

        if total_tagged % 100 == 0 and total_tagged > 0:
            logger.info(
                "tag_bills: progress — tagged=%d skipped=%d / total=%d",
                total_tagged, total_skipped, len(untagged),
            )

        # Rate-limit: brief pause between batches to avoid hammering the API
        if batch_start + batch_size < len(untagged):
            await asyncio.sleep(delay_between_batches)

    logger.info(
        "tag_bills: done — tagged=%d skipped=%d total_processed=%d",
        total_tagged, total_skipped, len(untagged),
    )


if __name__ == "__main__":
    async def _main() -> None:
        logging.basicConfig(level=logging.INFO)
        await tag_bills()

    asyncio.run(_main())
