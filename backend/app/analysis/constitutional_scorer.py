"""
Constitutional scoring for bills and legislators.
Uses claude-sonnet-4-6 with prompt caching for repeated article context.
"""
import json
import logging

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
