"""
Constitutional scoring for bills and legislators.

Two scoring paths live in this file:

  1. ConstitutionalScorer (below) — Sonnet-based, deeper per-bill analysis
     that also writes to BillConstitutionMapping. Designed for high-profile
     bills where the article-level breakdown matters. Not currently
     orchestrated; reserved for Phase 5+.

  2. run_constitutional_pipeline() (this module, end of file) — bulk
     Haiku-based pipeline that scores every voted bill and then computes
     each legislator's alignment from those scores. This is what
     POST /api/v1/sync/constitutional triggers.
"""
import asyncio
import json
import logging
import re

import anthropic
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.models import Bill, BillConstitutionMapping, ConstitutionArticle, Legislator, Vote

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
Você é um analista jurídico especializado na Constituição Federal do Brasil de 1988 (CF/88).
Sua função é avaliar se um projeto de lei (PL, PEC, MPV ou similar) apresenta riscos de \
inconstitucionalidade, com base exclusivamente no texto constitucional e na jurisprudência do STF.

Diretrizes:
- Fundamente sempre sua análise em artigos específicos da CF/88
- Distinga entre inconstitucionalidade formal (processo) e material (conteúdo)
- Considere precedentes do STF quando relevantes
- Seja objetivo e jurídico: não use posições políticas como fundamento
- Quando incerto, indique baixa confiança (< 0.5)

Responda APENAS em JSON válido, sem texto adicional."""

_SCORING_TEMPLATE = """\
Analise o seguinte projeto de lei quanto à sua constitucionalidade:

TIPO: {bill_type}
NÚMERO: {bill_number}/{bill_year}
EMENTA: {title}

Artigos constitucionais potencialmente relevantes:
{relevant_articles}

Responda em JSON com esta estrutura exata:
{{
  "risk_score": <float entre 0 e 1>,
  "risk_level": "<nenhum|baixo|médio|alto|crítico>",
  "formal_risk": <boolean>,
  "material_risk": <boolean>,
  "implicated_articles": [
    {{
      "article_ref": "<e.g. Art. 7, inciso XIII>",
      "relationship": "<compatible|conflicts|amends|regulates>",
      "reasoning": "<max 200 chars>",
      "confidence": <float 0-1>
    }}
  ],
  "summary_pt": "<explicação em português simples, máximo 300 chars>",
  "expert_review_needed": <boolean>,
  "confidence": <float 0-1>
}}"""


class ConstitutionalScorer:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic()

    async def _get_relevant_articles(self, db: AsyncSession, theme_tags: list[str]) -> str:
        if not theme_tags:
            return "(nenhum tema mapeado para este projeto)"

        result = await db.execute(
            select(ConstitutionArticle).where(
                ConstitutionArticle.theme_tags.overlap(theme_tags)
            ).limit(10)
        )
        articles = result.scalars().all()

        if not articles:
            return "(nenhum artigo pré-mapeado para estes temas)"

        return "\n".join(
            f"• {a.article_ref}: {a.title or ''}\n  {a.text_full[:300]}..."
            for a in articles
        )

    async def score_bill(self, bill: Bill, db: AsyncSession) -> dict:
        """Run constitutional analysis on a bill and persist results."""
        relevant_articles = await self._get_relevant_articles(db, bill.theme_tags or [])

        prompt = _SCORING_TEMPLATE.format(
            bill_type=bill.type or "PL",
            bill_number=bill.number,
            bill_year=bill.year,
            title=bill.title,
            relevant_articles=relevant_articles,
        )

        # Use prompt caching for the static system prompt
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )

        result = json.loads(response.content[0].text)

        bill.const_risk_score = result["risk_score"]

        for hit in result.get("implicated_articles", []):
            art_result = await db.execute(
                select(ConstitutionArticle).where(ConstitutionArticle.article_ref == hit["article_ref"])
            )
            article = art_result.scalar_one_or_none()
            if article:
                mapping = BillConstitutionMapping(
                    bill_id=bill.id,
                    article_id=article.id,
                    relationship=hit.get("relationship"),
                    ai_confidence=hit.get("confidence"),
                )
                await db.merge(mapping)

        await db.commit()
        return result

    async def compute_legislator_alignment(self, legislator_id: str, db: AsyncSession) -> float:
        """
        Compute constitutional alignment score for a legislator.
        +1 = consistently opposes high-risk bills / supports low-risk bills
        -1 = consistently supports high-risk bills
        """
        result = await db.execute(
            select(Vote, Bill)
            .join(Bill, Vote.bill_id == Bill.id)
            .where(Vote.legislator_id == legislator_id)
            .where(Bill.const_risk_score.isnot(None))
        )
        rows = result.all()

        if not rows:
            return 0.0

        score = 0.0
        weight_total = 0.0

        for vote, bill in rows:
            risk = bill.const_risk_score
            weight = abs(risk - 0.5) * 2
            weight_total += weight

            if risk > 0.5:
                score += weight * (1 if vote.vote_value == "não" else -1)
            else:
                score += weight * (1 if vote.vote_value == "sim" else -0.5)

        normalized = score / weight_total if weight_total > 0 else 0.0
        return max(-1.0, min(1.0, normalized))


# ────────────────────────────────────────────────────────────────────────────
# Bulk pipeline (Haiku) — what POST /api/v1/sync/constitutional triggers
# ────────────────────────────────────────────────────────────────────────────

_HAIKU_SYSTEM = """\
Você é um analista jurídico especializado na Constituição Federal do Brasil de \
1988. Avalie o risco de inconstitucionalidade do projeto abaixo. Responda \
APENAS em JSON válido, sem texto adicional."""

_HAIKU_TEMPLATE = """\
Projeto: {bill_type} {number}/{year}
Ementa: {title}
Resumo: {summary}

Responda com este JSON exato:
{{
  "risk_score": <float 0.0-1.0>,
  "risk_level": "<nenhum|baixo|medio|alto|critico>",
  "implicated_articles": ["Art. X", ...],
  "summary_pt": "<explicação em português simples, max 200 chars>",
  "confidence": <float 0.0-1.0>
}}"""


def _parse_score_json(raw: str) -> dict | None:
    """Strip markdown fences, parse JSON, validate risk_score is in [0,1]."""
    s = (raw or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.DOTALL).strip()
    if not s:
        return None
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return None
    rs = data.get("risk_score")
    if not isinstance(rs, (int, float)):
        return None
    if not 0.0 <= float(rs) <= 1.0:
        return None
    return data


async def _score_one_bill_haiku(
    client: anthropic.AsyncAnthropic, bill: Bill
) -> dict | None:
    """Single Haiku call → parsed JSON or None on any failure."""
    prompt = _HAIKU_TEMPLATE.format(
        bill_type=bill.type or "PL",
        number=bill.number,
        year=bill.year,
        title=(bill.title or "")[:400],
        summary=(bill.summary_official or "")[:600],
    )
    try:
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_HAIKU_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_score_json(resp.content[0].text)
    except Exception as exc:
        logger.warning("score_one_bill_haiku failed for bill %s: %s", bill.id, exc)
        return None


async def score_voted_bills(
    batch_size: int = 10,
    delay_between_batches: float = 0.5,
) -> tuple[int, int]:
    """
    Score every voted bill that doesn't yet have const_risk_score.

    Strategy: most-voted bills first (highest analytical signal),
    batches of `batch_size` concurrent Haiku calls, then a brief
    delay between batches to be polite to the API.

    Persists:
      - bills.const_risk_score
      - bills.summary_ai (only if it was NULL)

    Returns (scored, skipped) for the run.
    """
    client = anthropic.AsyncAnthropic()
    scored = 0
    skipped = 0

    # Build the work list: voted bills, no risk score yet, ordered by vote count
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("""
            SELECT b.id, b.type, b.number, b.year, b.title, b.summary_official, b.summary_ai
            FROM bills b
            JOIN (
                SELECT bill_id, COUNT(*) AS n
                FROM votes
                GROUP BY bill_id
            ) v ON v.bill_id = b.id
            WHERE b.const_risk_score IS NULL
            ORDER BY v.n DESC
        """))
        rows = result.all()

    logger.info("score_voted_bills: %d bills to score", len(rows))
    if not rows:
        return 0, 0

    for batch_start in range(0, len(rows), batch_size):
        batch = rows[batch_start : batch_start + batch_size]

        async def _score_row(r):
            stub = type("BillStub", (), {
                "id": r.id, "type": r.type, "number": r.number, "year": r.year,
                "title": r.title, "summary_official": r.summary_official,
            })()
            data = await _score_one_bill_haiku(client, stub)
            return r, data

        results = await asyncio.gather(
            *[_score_row(r) for r in batch], return_exceptions=True
        )

        # Persist this batch's results
        async with AsyncSessionLocal() as db:
            for item in results:
                if isinstance(item, Exception):
                    skipped += 1
                    continue
                r, data = item
                if data is None:
                    skipped += 1
                    continue
                rs = float(data["risk_score"])
                summary_pt = (data.get("summary_pt") or "")[:300] or None
                # Only set summary_ai if currently NULL
                if r.summary_ai is None and summary_pt:
                    await db.execute(text("""
                        UPDATE bills
                           SET const_risk_score = :rs,
                               summary_ai = :summary,
                               updated_at = now()
                         WHERE id = :id
                    """), {"rs": rs, "summary": summary_pt, "id": r.id})
                else:
                    await db.execute(text("""
                        UPDATE bills
                           SET const_risk_score = :rs,
                               updated_at = now()
                         WHERE id = :id
                    """), {"rs": rs, "id": r.id})
                scored += 1
            await db.commit()

        if (scored + skipped) and (scored + skipped) % 20 < batch_size:
            logger.info(
                "score_voted_bills: progress — scored=%d skipped=%d / total=%d",
                scored, skipped, len(rows),
            )

        if batch_start + batch_size < len(rows):
            await asyncio.sleep(delay_between_batches)

    logger.info(
        "score_voted_bills: DONE — scored=%d skipped=%d total=%d",
        scored, skipped, len(rows),
    )
    return scored, skipped


# ── Pure-SQL legislator alignment ────────────────────────────────────────────
_ALIGNMENT_SQL = text("""
    WITH alignments AS (
        SELECT
            v.legislator_id,
            SUM(
                CASE
                    WHEN b.const_risk_score > 0.6 AND v.vote_value = 'não'
                        THEN ABS(b.const_risk_score - 0.5) * 2
                    WHEN b.const_risk_score > 0.6 AND v.vote_value = 'sim'
                        THEN -1.0 * ABS(b.const_risk_score - 0.5) * 2
                    WHEN b.const_risk_score < 0.4 AND v.vote_value = 'sim'
                        THEN ABS(b.const_risk_score - 0.5) * 2 * 0.5
                    WHEN b.const_risk_score < 0.4 AND v.vote_value = 'não'
                        THEN -1.0 * ABS(b.const_risk_score - 0.5) * 2 * 0.5
                    ELSE 0
                END
            ) AS signed_sum,
            SUM(
                CASE
                    WHEN b.const_risk_score > 0.6 AND v.vote_value IN ('sim','não')
                        THEN ABS(b.const_risk_score - 0.5) * 2
                    WHEN b.const_risk_score < 0.4 AND v.vote_value IN ('sim','não')
                        THEN ABS(b.const_risk_score - 0.5) * 2 * 0.5
                    ELSE 0
                END
            ) AS abs_sum
        FROM votes v
        JOIN bills b ON v.bill_id = b.id
        WHERE b.const_risk_score IS NOT NULL
        GROUP BY v.legislator_id
    )
    UPDATE legislators l
    SET const_alignment_score =
        GREATEST(-1.0, LEAST(1.0,
            a.signed_sum / NULLIF(a.abs_sum, 0)
        ))
    FROM alignments a
    WHERE l.id = a.legislator_id
      AND a.abs_sum > 0
""")


async def compute_constitutional_alignment() -> int:
    """
    Recompute legislators.const_alignment_score from current vote +
    bill.const_risk_score data.

    Spec math (per vote):
      weight = abs(risk - 0.5) * 2     # 0 at neutral, 1 at extremes

      risk > 0.6 + voted 'não'  → +weight       (correctly opposing risky bill)
      risk > 0.6 + voted 'sim'  → -weight       (supporting risky bill)
      risk < 0.4 + voted 'sim'  → +weight * 0.5 (supporting safe bill, half)
      risk < 0.4 + voted 'não'  → -weight * 0.5
      0.4 <= risk <= 0.6        → 0             (no signal, borderline)
      vote_value not in (sim,não) → 0           (abstain/absent → no signal)

    Per-legislator: score = sum(signed) / sum(|signed|), bounded to [-1, 1].
    Idempotent.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(_ALIGNMENT_SQL)
        await db.commit()
    n = result.rowcount or 0
    logger.info("compute_constitutional_alignment: updated %d legislators", n)
    return n


async def run_constitutional_pipeline() -> None:
    """Top-level: score every unscored voted bill, then recompute alignments."""
    logger.info("run_constitutional_pipeline: starting")
    scored, skipped = await score_voted_bills()
    n = await compute_constitutional_alignment()
    logger.info(
        "run_constitutional_pipeline: DONE — bills scored=%d skipped=%d, "
        "legislators aligned=%d",
        scored, skipped, n,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_constitutional_pipeline())
