"""
Query classifier for Farol.
Uses claude-haiku-4-5 to extract both the intent category and named entities
in a single cheap call, avoiding a separate NER pass.
"""
import json
import logging
import re
from dataclasses import dataclass, field

import anthropic

logger = logging.getLogger(__name__)

CATEGORIES = (
    "legislator_profile",
    "bill_lookup",
    "vote_pattern",
    "donor_exposure",
    "theme_filter",
    "constitutional_risk",
    "coalition_map",
    "general",
)

THEME_SLUGS = (
    "trabalho", "meio-ambiente", "saude", "educacao", "seguranca-publica",
    "agronegocio", "tributacao", "direitos-lgbtqia", "armas", "religiao",
    "indigenas", "midia", "reforma-politica",
)

_CLASSIFY_SYSTEM = """\
Você é um classificador de consultas para uma plataforma legislativa brasileira.
Responda APENAS em JSON válido, sem texto adicional."""

_CLASSIFY_TEMPLATE = """\
Analise a pergunta e retorne JSON com esta estrutura exata:
{{
  "category": "<uma de: {categories}>",
  "entities": {{
    "legislator_name": "<nome parcial ou null>",
    "state_uf": "<sigla UF maiúscula ou null>",
    "theme_slug": "<um de: {theme_slugs} ou null>",
    "bill_type": "<PL|PEC|MPV|PDL|PLP ou null>",
    "bill_number": <inteiro ou null>,
    "bill_year": <inteiro ou null>,
    "keyword": "<termo de busca livre ou null>"
  }}
}}

Regras de classificação:
- legislator_profile: perfil, partido, cargo, mandato, quem é, escolaridade, deputados de um estado, listar parlamentares por UF
- bill_lookup: projeto de lei específico, busca por número, ementa, tema
- vote_pattern: como votou, histórico de votos de um deputado
- donor_exposure: financiamento, doadores, quem financia, dinheiro de campanha
- theme_filter: projetos sobre um tema (saúde, educação, etc.)
- constitutional_risk: risco constitucional, inconstitucional, CF/88
- coalition_map: coalizão comportamental, bloco de votação, bancada, "Bloco Bolsonarista", "Coalização Governista", "Centrão", "quais são as coalizões", quais deputados pertencem a um bloco. Coloque o nome da coalizão (ex: "Bolsonarista", "Governista", "Centrão") no campo keyword quando houver.
- general: qualquer outra coisa

Pergunta: {query}"""


@dataclass
class ClassifyResult:
    category: str
    legislator_name: str | None = None
    state_uf: str | None = None
    theme_slug: str | None = None
    bill_type: str | None = None
    bill_number: int | None = None
    bill_year: int | None = None
    keyword: str | None = None


async def classify_query(query: str, client: anthropic.AsyncAnthropic) -> ClassifyResult:
    prompt = _CLASSIFY_TEMPLATE.format(
        categories="|".join(CATEGORIES),
        theme_slugs="|".join(THEME_SLUGS),
        query=query,
    )
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=_CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences Haiku sometimes adds despite instructions
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
        if not raw:
            logger.warning("classify_query: empty response from model, falling back to general")
            return ClassifyResult(category="general", keyword=query[:100])
        logger.debug("classify_query raw: %s", raw[:200])
        data = json.loads(raw)
        entities = data.get("entities", {})
        category = data.get("category", "general")
        if category not in CATEGORIES:
            category = "general"
        return ClassifyResult(
            category=category,
            legislator_name=entities.get("legislator_name"),
            state_uf=entities.get("state_uf"),
            theme_slug=entities.get("theme_slug"),
            bill_type=entities.get("bill_type"),
            bill_number=entities.get("bill_number"),
            bill_year=entities.get("bill_year"),
            keyword=entities.get("keyword"),
        )
    except Exception as exc:
        logger.warning("classify_query failed (%s), falling back to general", exc)
        return ClassifyResult(category="general", keyword=query[:100])
