"""
DB retrieval functions for each query category.
Each function returns (context_text, sources_list).
context_text is injected into the Farol prompt.
sources_list is returned to the frontend for clickable citations.
"""
import logging
import re
from dataclasses import dataclass, replace

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.farol.classifier import ClassifyResult


# ── Lei → PL lookup ──────────────────────────────────────────────────────────
# When users ask "Como votaram na Lei X" Farol needs to find the PL/PEC
# that became that lei. This map is curated for laws whose source bill we
# care about. New entries: add the lei in both punctuated and bare forms.
LEI_TO_PL_MAP: dict[str, tuple[str, int, int]] = {
    # Lei 15.270/2025 — Reforma do IR (PL 1087/2025, camara_id 2487436)
    "15.270/2025": ("PL", 1087, 2025),
    "15270/2025":  ("PL", 1087, 2025),
    "15270":       ("PL", 1087, 2025),
    # Lei 14.611/2023 — Igualdade Salarial (PL 1085/2023, camara_id 2351179)
    "14.611/2023": ("PL", 1085, 2023),
    "14611/2023":  ("PL", 1085, 2023),
    "14611":       ("PL", 1085, 2023),
}


def extract_lei_number(query: str) -> str | None:
    """
    Pull the lei number from a free-form Portuguese query, e.g.
    'Como votaram na Lei 15.270/2025?' → '15270/2025'
    'Lei nº 15.270 de 2025'           → '15270/2025'
    'Lei 15270'                        → '15270'
    Returns the digit-only form (suitable for LEI_TO_PL_MAP lookup), or None.
    """
    if not query:
        return None
    # Pattern 1: "Lei [nº] X.YYY/AAAA" or "Lei X.YYY/AAAA"
    m = re.search(
        r"lei\s*n?[º°.]?\s*(\d+(?:[.,]\d+)?)\s*(?:/|\bde\b)\s*(\d{4})",
        query,
        re.IGNORECASE,
    )
    if m:
        num = m.group(1).replace(".", "").replace(",", "")
        year = m.group(2)
        return f"{num}/{year}"
    # Pattern 2: bare "Lei X.YYY"
    m = re.search(
        r"lei\s*n?[º°.]?\s*(\d+(?:[.,]\d+)?)",
        query,
        re.IGNORECASE,
    )
    if m:
        num = m.group(1).replace(".", "").replace(",", "")
        return num
    return None


def apply_lei_overrides(query: str, intent: ClassifyResult) -> ClassifyResult:
    """
    If the user query references a Lei number that maps to a known
    PL/PEC, populate intent.bill_type/number/year from our curated map.

    The mapping ALWAYS wins over the classifier's guess when a Lei
    number is present in the query: Haiku tends to parse "Lei 15.270/2025"
    as "PL 15270/2025", which is wrong (the PL that *became* that lei
    is PL 1087/2025). The curated map is the source of truth here.
    """
    lei = extract_lei_number(query or "")
    if not lei:
        return intent
    mapped = LEI_TO_PL_MAP.get(lei)
    if not mapped:
        return intent
    btype, bnumber, byear = mapped
    logger.info(
        "apply_lei_overrides: lei=%s → %s %d/%d (was %s %s/%s)",
        lei, btype, bnumber, byear,
        intent.bill_type, intent.bill_number, intent.bill_year,
    )
    return replace(
        intent,
        bill_type=btype,
        bill_number=bnumber,
        bill_year=byear,
    )
from app.models import (
    BehavioralCluster,
    Bill,
    BillConstitutionMapping,
    Donor,
    DonorLink,
    Legislator,
    LegislatorTheme,
    Party,
    Theme,
    Vote,
)

logger = logging.getLogger(__name__)

SOURCE_LEGISLATOR = "legislator"
SOURCE_BILL = "bill"
SOURCE_VOTE = "vote"


@dataclass
class RetrievalResult:
    context: str
    sources: list[dict]


async def retrieve(intent: ClassifyResult, db: AsyncSession) -> RetrievalResult:
    """Dispatch to the correct retriever based on classified intent."""
    handlers = {
        "legislator_profile": _legislator_profile,
        "bill_lookup": _bill_lookup,
        "vote_pattern": _vote_pattern,
        "donor_exposure": _donor_exposure,
        "theme_filter": _theme_filter,
        "constitutional_risk": _constitutional_risk,
        "coalition_map": _coalition_map,
        "general": _general,
    }
    handler = handlers.get(intent.category, _general)
    try:
        return await handler(intent, db)
    except Exception as exc:
        logger.warning("retriever %s failed: %s", intent.category, exc)
        return RetrievalResult(
            context="(Não foi possível recuperar dados do banco neste momento.)",
            sources=[],
        )


# ── Individual retrievers ──────────────────────────────────────────────────────

async def _legislator_profile(intent: ClassifyResult, db: AsyncSession) -> RetrievalResult:
    # State-only queries list an entire delegation (up to 20); name searches stay tight (5).
    limit = 20 if (intent.state_uf and not intent.legislator_name) else 5

    q = (
        select(Legislator, Party)
        .outerjoin(Party, Legislator.nominal_party_id == Party.id)
    )
    if intent.legislator_name:
        pattern = f"%{intent.legislator_name.lower()}%"
        q = q.where(
            func.lower(Legislator.name).like(pattern)
            | func.lower(Legislator.display_name).like(pattern)
        )
    if intent.state_uf:
        q = q.where(Legislator.state_uf == intent.state_uf.upper())
    q = q.limit(limit)

    rows = (await db.execute(q)).all()
    if not rows:
        return RetrievalResult(
            context="Nenhum deputado encontrado com esses critérios.",
            sources=[],
        )

    sources = []
    lines = []
    for leg, party in rows:
        sources.append({
            "type": SOURCE_LEGISLATOR,
            "id": str(leg.id),
            "name": leg.display_name or leg.name,
        })
        lines.append(
            f"- {leg.display_name or leg.name} ({party.acronym if party else '—'} / {leg.state_uf})"
            f" | alinhamento CF/88: {_fmt_score(leg.const_alignment_score)}"
            f" | disciplina partidária: {_fmt_score(leg.party_discipline_score)}"
            f" | ausências: {_fmt_pct(leg.absence_rate)}"
        )

    # Also pull theme breakdown for the first match
    if rows:
        first_leg, _ = rows[0]
        theme_rows = (
            await db.execute(
                select(LegislatorTheme, Theme)
                .join(Theme, LegislatorTheme.theme_id == Theme.id)
                .where(LegislatorTheme.legislator_id == first_leg.id)
                .order_by(LegislatorTheme.position_score.desc().nullslast())
                .limit(5)
            )
        ).all()
        if theme_rows:
            theme_lines = [
                f"  • {t.label_pt}: {lt.votes_favorable}✓ / {lt.votes_against}✗ "
                f"(score: {_fmt_score(lt.position_score)})"
                for lt, t in theme_rows
            ]
            lines.append(f"\nPosições temáticas de {first_leg.display_name or first_leg.name}:")
            lines.extend(theme_lines)

    return RetrievalResult(context="\n".join(lines), sources=sources)


async def _bill_lookup(intent: ClassifyResult, db: AsyncSession) -> RetrievalResult:
    q = select(Bill).limit(6)

    if intent.bill_type and intent.bill_number and intent.bill_year:
        q = q.where(
            Bill.type == intent.bill_type.upper(),
            Bill.number == intent.bill_number,
            Bill.year == intent.bill_year,
        )
    elif intent.keyword:
        q = q.where(Bill.title.ilike(f"%{intent.keyword}%"))
    elif intent.bill_type:
        q = q.where(Bill.type == intent.bill_type.upper())
        if intent.bill_year:
            q = q.where(Bill.year == intent.bill_year)
    else:
        q = q.order_by(Bill.presentation_date.desc().nullslast())

    bills = (await db.execute(q)).scalars().all()
    if not bills:
        return RetrievalResult(context="Nenhum projeto encontrado com esses critérios.", sources=[])

    sources = []
    lines = []
    for b in bills:
        label = f"{b.type} {b.number}/{b.year}"
        sources.append({"type": SOURCE_BILL, "id": str(b.id), "label": label})
        risk = f" | risco CF/88: {b.const_risk_score:.2f}" if b.const_risk_score is not None else ""
        lines.append(
            f"- {label}: {b.title[:120]}"
            f"\n  Status: {b.status or 'Em tramitação'}"
            f"{risk}"
            f"{' | URGÊNCIA' if b.urgency_regime else ''}"
            f"\n  Temas: {', '.join(b.theme_tags or []) or '(não classificado)'}"
        )

    return RetrievalResult(context="\n".join(lines), sources=sources)


async def _vote_pattern(intent: ClassifyResult, db: AsyncSession) -> RetrievalResult:
    # ── Branch A: bill-centric — "como votaram na PEC 45/2019?" ──────────────
    if intent.bill_type and intent.bill_number and intent.bill_year and not intent.legislator_name:
        return await _vote_pattern_bill(intent, db)

    # ── Branch B: legislator-centric — "como votou Lira?" ────────────────────
    if not intent.legislator_name:
        return RetrievalResult(
            context=(
                "Especifique o nome do deputado ou o projeto de lei (ex: PEC 45/2019) "
                "para consultar o histórico de votações."
            ),
            sources=[],
        )

    pattern = f"%{intent.legislator_name.lower()}%"
    leg_result = await db.execute(
        select(Legislator).where(
            func.lower(Legislator.name).like(pattern)
            | func.lower(Legislator.display_name).like(pattern)
        ).limit(1)
    )
    leg = leg_result.scalar_one_or_none()
    if not leg:
        return RetrievalResult(
            context=f"Deputado '{intent.legislator_name}' não encontrado.",
            sources=[],
        )

    vote_rows = (
        await db.execute(
            select(Vote, Bill)
            .join(Bill, Vote.bill_id == Bill.id)
            .where(Vote.legislator_id == leg.id)
            .order_by(Vote.voted_at.desc().nullslast())
            .limit(20)
        )
    ).all()

    sources: list[dict] = [
        {"type": SOURCE_LEGISLATOR, "id": str(leg.id), "name": leg.display_name or leg.name}
    ]

    if not vote_rows:
        return RetrievalResult(
            context=f"{leg.display_name or leg.name}: nenhuma votação registrada.", sources=sources
        )

    total = len(vote_rows)
    sim = sum(1 for v, _ in vote_rows if v.vote_value == "sim")
    nao = sum(1 for v, _ in vote_rows if v.vote_value == "não")
    aus = sum(1 for v, _ in vote_rows if v.vote_value == "ausente")
    conflicts = sum(1 for v, _ in vote_rows if v.donor_conflict_flag)

    lines = [
        f"Deputado: {leg.display_name or leg.name} ({leg.state_uf})",
        f"Últimas {total} votações: {sim} sim / {nao} não / {aus} ausente",
        f"Conflitos de doador sinalizados: {conflicts}",
        "",
        "Votações recentes:",
    ]
    for vote, bill in vote_rows[:10]:
        label = f"{bill.type} {bill.number}/{bill.year}"
        sources.append({"type": SOURCE_VOTE, "bill_label": label, "vote_value": vote.vote_value})
        flag = " ⚠️ conflito doador" if vote.donor_conflict_flag else ""
        lines.append(f"  • {label} — votou: {vote.vote_value}{flag}")

    return RetrievalResult(context="\n".join(lines), sources=sources)


async def _vote_pattern_bill(intent: ClassifyResult, db: AsyncSession) -> RetrievalResult:
    """Return vote breakdown for a specific bill (type + number + year)."""
    bill_label = f"{intent.bill_type.upper()} {intent.bill_number}/{intent.bill_year}"

    # Verify bill exists
    bill_result = await db.execute(
        select(Bill).where(
            Bill.type == intent.bill_type.upper(),
            Bill.number == intent.bill_number,
            Bill.year == intent.bill_year,
        ).limit(1)
    )
    bill = bill_result.scalar_one_or_none()
    if not bill:
        return RetrievalResult(
            context=(
                f"{bill_label} não encontrado na base. "
                f"Verifique o número e ano, ou sincronize os dados."
            ),
            sources=[],
        )

    # Fetch all votes for this bill with legislator + party info
    rows = (
        await db.execute(
            select(Vote, Legislator, Party)
            .join(Legislator, Vote.legislator_id == Legislator.id)
            .outerjoin(Party, Legislator.nominal_party_id == Party.id)
            .where(Vote.bill_id == bill.id)
            .order_by(Vote.vote_value, Legislator.state_uf)
            .limit(50)
        )
    ).all()

    sources: list[dict] = [{"type": SOURCE_BILL, "id": str(bill.id), "label": bill_label}]

    if not rows:
        return RetrievalResult(
            context=(
                f"{bill_label}: projeto encontrado, mas sem votos registrados na base. "
                f"Sincronize os votos via POST /api/v1/sync/bills/{bill.camara_id}/votes"
            ),
            sources=sources,
        )

    # Tally by vote_value across ALL votes (not just top 50)
    all_votes_result = await db.execute(
        select(Vote.vote_value, func.count().label("n"))
        .where(Vote.bill_id == bill.id)
        .group_by(Vote.vote_value)
    )
    tally: dict[str, int] = {r.vote_value: r.n for r in all_votes_result.all()}
    total_votes = sum(tally.values())
    sim_n   = tally.get("sim", 0)
    nao_n   = tally.get("não", 0)
    abst_n  = tally.get("abstenção", 0)
    aus_n   = tally.get("ausente", 0)

    lines = [
        f"Resultado da votação — {bill_label}:",
        f"  Título: {bill.title[:120]}",
        f"  Status: {bill.status or 'Em tramitação'}",
        "",
        f"Placar ({total_votes} deputados):",
        f"  ✅ Sim:        {sim_n}",
        f"  ❌ Não:        {nao_n}",
        f"  🟡 Abstenção:  {abst_n}",
        f"  ⬜ Ausente:    {aus_n}",
        "",
        f"Amostra de votos (até 50, ordenados por posição / UF):",
    ]
    for vote, leg, party in rows:
        party_str = party.acronym if party else "—"
        lines.append(
            f"  • {leg.display_name or leg.name} ({party_str}/{leg.state_uf})"
            f" — {vote.vote_value}"
        )
        sources.append({
            "type": SOURCE_VOTE,
            "legislator_id": str(leg.id),
            "name": leg.display_name or leg.name,
            "vote_value": vote.vote_value,
        })

    return RetrievalResult(context="\n".join(lines), sources=sources)


# ── Funding-source classification ─────────────────────────────────────────────
# Post-2015 ban (Lei 13.165/2015), Brazilian campaign donations come almost
# entirely from public party-fund transfers (FEFC) — visible as donor names
# like "Direção Nacional" or "Direção Estadual/Distrital". Companies were
# banned outright; only narrow legal exceptions remain. We classify each
# donor row inline so the retriever doesn't need a denormalised column.

def _funding_source_case():
    """SQLAlchemy CASE returning 'party_fund' | 'company' | 'individual' | 'other'."""
    return case(
        (
            or_(
                func.lower(Donor.name).like("%direção%"),
                func.lower(Donor.name).like("%direcao%"),
                func.lower(Donor.name).like("%fundo eleitoral%"),
                func.lower(Donor.name).like("%fefc%"),
            ),
            "party_fund",
        ),
        (Donor.entity_type == "pessoa_juridica", "company"),
        (Donor.entity_type == "pessoa_fisica", "individual"),
        else_="other",
    )


_SOURCE_LABEL_PT = {
    "party_fund":  "Fundo partidário/FEFC",
    "individual":  "Pessoa física",
    "company":     "Empresa (PJ)",
    "other":       "Outros",
}


async def _donor_exposure(intent: ClassifyResult, db: AsyncSession) -> RetrievalResult:
    """
    Donor exposure analysis tuned for post-2015 Brazilian electoral reality.

    Per-deputy: total received, funding-source breakdown, top individual donors,
    top corporate donors. Cross-deputy: lists individuals who funded multiple
    deputies (potential proxy / coordination signal).
    """
    # ── No legislator named → cross-deputy coordination view ──────────────────
    if not intent.legislator_name:
        # Top individuals (CPF) who funded the largest number of distinct deputies
        coord = (
            await db.execute(
                select(
                    Donor.id,
                    Donor.name,
                    func.count(DonorLink.legislator_id.distinct()).label("leg_count"),
                    func.sum(DonorLink.amount_brl).label("total"),
                )
                .join(DonorLink, Donor.id == DonorLink.donor_id)
                .where(Donor.entity_type == "pessoa_fisica")
                .group_by(Donor.id, Donor.name)
                .having(func.count(DonorLink.legislator_id.distinct()) > 1)
                .order_by(text("leg_count DESC"), text("total DESC"))
                .limit(10)
            )
        ).all()

        # Aggregate flow by funding source across the whole base
        flow = (
            await db.execute(
                select(
                    _funding_source_case().label("src"),
                    func.sum(DonorLink.amount_brl).label("total"),
                )
                .join(DonorLink, Donor.id == DonorLink.donor_id)
                .group_by(text("src"))
                .order_by(text("total DESC"))
            )
        ).all()
        flow_total = sum(row.total or 0 for row in flow) or 1

        lines = ["Origem do financiamento eleitoral 2022 — visão geral:"]
        for row in flow:
            pct = (row.total or 0) / flow_total * 100
            lines.append(
                f"  • {_SOURCE_LABEL_PT.get(row.src, row.src)}: "
                f"R$ {row.total:,.2f} ({pct:.1f}%)"
            )

        if coord:
            lines.append("")
            lines.append("Doadores individuais que financiaram múltiplos deputados:")
            for r in coord:
                lines.append(
                    f"  • {r.name} — financiou {r.leg_count} deputados "
                    f"(R$ {r.total:,.2f} total)"
                )
        else:
            lines.append("")
            lines.append("(Nenhum doador individual financiou mais de um deputado.)")

        return RetrievalResult(context="\n".join(lines), sources=[])

    # ── Legislator named → per-deputy funding profile ─────────────────────────
    pattern = f"%{intent.legislator_name.lower()}%"
    leg_result = await db.execute(
        select(Legislator).where(
            func.lower(Legislator.name).like(pattern)
            | func.lower(Legislator.display_name).like(pattern)
        ).limit(1)
    )
    leg = leg_result.scalar_one_or_none()
    if not leg:
        return RetrievalResult(
            context=f"Deputado '{intent.legislator_name}' não encontrado.",
            sources=[],
        )

    sources: list[dict] = [
        {"type": SOURCE_LEGISLATOR, "id": str(leg.id), "name": leg.display_name or leg.name}
    ]

    # 1. Funding-source breakdown for this deputy
    breakdown = (
        await db.execute(
            select(
                _funding_source_case().label("src"),
                func.sum(DonorLink.amount_brl).label("total"),
            )
            .join(DonorLink, Donor.id == DonorLink.donor_id)
            .where(DonorLink.legislator_id == leg.id)
            .group_by(text("src"))
            .order_by(text("total DESC"))
        )
    ).all()

    if not breakdown:
        return RetrievalResult(
            context=(
                f"O deputado {leg.display_name or leg.name} ({leg.state_uf}) está na "
                f"base, mas não há registros de doações de campanha vinculadas "
                f"(eleições 2022)."
            ),
            sources=sources,
        )

    total = sum(row.total or 0 for row in breakdown) or 1
    lines = [
        f"Financiamento eleitoral 2022 — {leg.display_name or leg.name} ({leg.state_uf}):",
        f"Total recebido: R$ {total:,.2f}",
        "",
        "Origem do dinheiro:",
    ]
    for row in breakdown:
        pct = (row.total or 0) / total * 100
        lines.append(
            f"  • {_SOURCE_LABEL_PT.get(row.src, row.src)}: "
            f"R$ {row.total:,.2f} ({pct:.1f}%)"
        )

    # 2. Top individual donors (CPF, excluding party-fund transfers)
    top_indiv = (
        await db.execute(
            select(
                Donor.name,
                func.sum(DonorLink.amount_brl).label("total"),
            )
            .join(DonorLink, Donor.id == DonorLink.donor_id)
            .where(
                DonorLink.legislator_id == leg.id,
                Donor.entity_type == "pessoa_fisica",
                ~func.lower(Donor.name).like("%direção%"),
                ~func.lower(Donor.name).like("%direcao%"),
            )
            .group_by(Donor.name)
            .order_by(text("total DESC"))
            .limit(7)
        )
    ).all()

    if top_indiv:
        lines.append("")
        lines.append("Maiores doadores pessoa física:")
        for r in top_indiv:
            lines.append(f"  • {r.name} — R$ {r.total:,.2f}")

    # 3. Corporate donors (rare post-ban, but always interesting)
    top_corp = (
        await db.execute(
            select(
                Donor.name,
                func.sum(DonorLink.amount_brl).label("total"),
            )
            .join(DonorLink, Donor.id == DonorLink.donor_id)
            .where(
                DonorLink.legislator_id == leg.id,
                Donor.entity_type == "pessoa_juridica",
                ~func.lower(Donor.name).like("%direção%"),
                ~func.lower(Donor.name).like("%direcao%"),
            )
            .group_by(Donor.name)
            .order_by(text("total DESC"))
            .limit(5)
        )
    ).all()

    if top_corp:
        lines.append("")
        lines.append("Doadores pessoa jurídica:")
        for r in top_corp:
            lines.append(f"  • {r.name} — R$ {r.total:,.2f}")

    lines.append("")
    lines.append(
        "Nota: desde a Lei 13.165/2015, doações de empresas são proibidas, "
        "exceto em casos legais específicos. A maior parte do financiamento "
        "vem do FEFC (fundo público distribuído pelos partidos)."
    )

    return RetrievalResult(context="\n".join(lines), sources=sources)


async def _theme_filter(intent: ClassifyResult, db: AsyncSession) -> RetrievalResult:
    q = select(Bill).order_by(Bill.presentation_date.desc().nullslast()).limit(8)
    if intent.theme_slug:
        q = q.where(Bill.theme_tags.any(intent.theme_slug))
    elif intent.keyword:
        q = q.where(Bill.theme_tags.any(intent.keyword))

    bills = (await db.execute(q)).scalars().all()
    if not bills:
        theme_label = intent.theme_slug or intent.keyword or "esse tema"
        return RetrievalResult(
            context=(
                f"Nenhum projeto sobre '{theme_label}' encontrado na base ainda. "
                f"Possíveis razões: (1) os projetos ainda não foram importados — execute a sincronização; "
                f"(2) os projetos existentes ainda não receberam tags temáticas — isso é feito pelo "
                f"pipeline de NLP na Fase 2; (3) o tema pode ter uma grafia diferente na base. "
                f"Temas disponíveis: trabalho, meio-ambiente, saude, educacao, seguranca-publica, "
                f"agronegocio, tributacao."
            ),
            sources=[],
        )

    sources = []
    lines = [f"Projetos sobre '{intent.theme_slug or intent.keyword or 'tema não especificado'}':\n"]
    for b in bills:
        label = f"{b.type} {b.number}/{b.year}"
        sources.append({"type": SOURCE_BILL, "id": str(b.id), "label": label})
        risk = f" | risco CF/88: {b.const_risk_score:.2f}" if b.const_risk_score is not None else ""
        lines.append(f"- {label}: {b.title[:100]}\n  Status: {b.status or 'Em tramitação'}{risk}")

    return RetrievalResult(context="\n".join(lines), sources=sources)


async def _constitutional_risk(intent: ClassifyResult, db: AsyncSession) -> RetrievalResult:
    q = (
        select(
            Bill,
            func.count(BillConstitutionMapping.article_id)
            .filter(BillConstitutionMapping.relationship == "conflicts")
            .label("conflict_count"),
        )
        .outerjoin(BillConstitutionMapping, Bill.id == BillConstitutionMapping.bill_id)
        .where(Bill.const_risk_score > 0.5)
        .group_by(Bill.id)
        .order_by(Bill.const_risk_score.desc())
        .limit(8)
    )
    if intent.keyword:
        q = q.where(Bill.title.ilike(f"%{intent.keyword}%"))

    rows = (await db.execute(q)).all()
    if not rows:
        # Check if there are any bills at all vs scoring just not run yet
        bill_count = (await db.execute(select(func.count()).select_from(Bill))).scalar_one()
        if bill_count == 0:
            return RetrievalResult(
                context=(
                    "AVISO DE DISPONIBILIDADE DE DADOS: A base de projetos de lei ainda está vazia. "
                    "Execute a sincronização inicial para importar os projetos da Câmara."
                ),
                sources=[],
            )
        return RetrievalResult(
            context=(
                f"AVISO DE DISPONIBILIDADE DE DADOS: Há {bill_count} projetos de lei na base, "
                f"mas nenhum foi analisado pelo sistema de scoring constitucional ainda. "
                f"A análise de risco constitucional (usando IA + CF/88) será executada "
                f"automaticamente após a importação dos dados. "
                f"Para projetos em tramitação agora, tente perguntar por tema (ex: 'saúde', 'trabalho') "
                f"ou pelo número do projeto."
            ),
            sources=[],
        )

    sources = []
    lines = ["Projetos com maior risco constitucional (score > 0.5):\n"]
    for bill, conflict_count in rows:
        label = f"{bill.type} {bill.number}/{bill.year}"
        sources.append({"type": SOURCE_BILL, "id": str(bill.id), "label": label})
        lines.append(
            f"- {label}: {bill.title[:100]}"
            f"\n  Risco: {bill.const_risk_score:.2f}"
            f" | Artigos conflitantes: {conflict_count}"
            f"{' | URGÊNCIA' if bill.urgency_regime else ''}"
        )

    return RetrievalResult(context="\n".join(lines), sources=sources)


SOURCE_CLUSTER = "cluster"


async def _coalition_map(intent: ClassifyResult, db: AsyncSession) -> RetrievalResult:
    """
    Two modes:
      A) Specific coalition (intent.keyword has a name like "Bolsonarista" /
         "Governista" / "Centrão") — fuzzy ILIKE match, return up to 30
         members with party + state, plus cohesion + dominant themes.
      B) Overview (no keyword) — list every cluster with member_count, top
         5 parties, and dominant themes.
    """
    keyword = (intent.keyword or "").strip()

    # ── Mode B: overview ────────────────────────────────────────────────────
    if not keyword:
        cluster_rows = (
            await db.execute(
                select(BehavioralCluster).order_by(
                    BehavioralCluster.member_count.desc().nullslast()
                )
            )
        ).scalars().all()
        if not cluster_rows:
            return RetrievalResult(
                context=(
                    "Nenhuma coalizão comportamental foi calculada ainda. "
                    "As coalizões são geradas a partir do histórico real "
                    "de votações dos deputados."
                ),
                sources=[],
            )

        # Party distribution per cluster — single query
        party_dist_rows = (
            await db.execute(
                select(
                    Legislator.behavioral_cluster_id,
                    Party.acronym,
                    func.count(Legislator.id).label("n"),
                )
                .outerjoin(Party, Legislator.nominal_party_id == Party.id)
                .where(Legislator.behavioral_cluster_id.is_not(None))
                .group_by(Legislator.behavioral_cluster_id, Party.acronym)
            )
        ).all()
        party_dist: dict[str, list[tuple[str, int]]] = {}
        for r in party_dist_rows:
            cid = str(r.behavioral_cluster_id)
            party_dist.setdefault(cid, []).append((r.acronym or "(sem)", r.n))

        lines = [
            f"Coalizões comportamentais do Congresso ({len(cluster_rows)} blocos identificados):",
            "",
        ]
        sources: list[dict] = []
        for c in cluster_rows:
            top_parties = sorted(party_dist.get(str(c.id), []), key=lambda x: -x[1])[:5]
            parties_str = ", ".join(f"{p} ({n})" for p, n in top_parties) or "—"
            cohesion_pct = f"{round((c.cohesion_score or 0) * 100)}%"
            themes = ", ".join((c.dominant_themes or [])[:4]) or "—"
            lines.append(f"• **{c.label}** — {c.member_count or 0} deputados, cohesão {cohesion_pct}")
            lines.append(f"  Partidos: {parties_str}")
            lines.append(f"  Temas: {themes}")
            lines.append("")
            sources.append({
                "type": SOURCE_CLUSTER,
                "id": str(c.id),
                "label": c.label,
            })
        return RetrievalResult(context="\n".join(lines).strip(), sources=sources)

    # ── Mode A: specific coalition ─────────────────────────────────────────
    cluster = (
        await db.execute(
            select(BehavioralCluster)
            .where(BehavioralCluster.label.ilike(f"%{keyword}%"))
            .order_by(BehavioralCluster.member_count.desc().nullslast())
            .limit(1)
        )
    ).scalar_one_or_none()

    if not cluster:
        return RetrievalResult(
            context=(
                f"Nenhuma coalizão correspondente a '{keyword}' foi encontrada. "
                f"As coalizões disponíveis são geradas a partir das votações; "
                f"você pode pedir 'quais são as coalizões do Congresso?' "
                f"para ver a lista completa."
            ),
            sources=[],
        )

    # Members of this cluster (capped at 30)
    member_rows = (
        await db.execute(
            select(Legislator, Party)
            .outerjoin(Party, Legislator.nominal_party_id == Party.id)
            .where(Legislator.behavioral_cluster_id == cluster.id)
            .order_by(Party.acronym, Legislator.display_name)
            .limit(30)
        )
    ).all()

    # Party tally (full, even if member preview is capped)
    party_tally_rows = (
        await db.execute(
            select(Party.acronym, func.count(Legislator.id).label("n"))
            .outerjoin(Party, Legislator.nominal_party_id == Party.id)
            .where(Legislator.behavioral_cluster_id == cluster.id)
            .group_by(Party.acronym)
            .order_by(func.count(Legislator.id).desc())
        )
    ).all()
    parties_str = ", ".join(f"{r.acronym or '(sem)'} ({r.n})" for r in party_tally_rows[:8])

    cohesion_pct = f"{round((cluster.cohesion_score or 0) * 100)}%"
    themes = ", ".join((cluster.dominant_themes or [])[:5]) or "—"

    lines = [
        f"## {cluster.label}",
        "",
        f"**{cluster.member_count or 0} deputados** · cohesão **{cohesion_pct}**",
        f"Partidos representados: {parties_str}",
        f"Temas dominantes: {themes}",
        "",
        f"Membros (até 30 mais relevantes por partido):",
    ]
    sources: list[dict] = [{
        "type": SOURCE_CLUSTER,
        "id": str(cluster.id),
        "label": cluster.label,
    }]
    for leg, party in member_rows:
        party_str = party.acronym if party else "—"
        lines.append(
            f"  • {leg.display_name or leg.name} ({party_str}/{leg.state_uf})"
        )
        sources.append({
            "type": SOURCE_LEGISLATOR,
            "id": str(leg.id),
            "name": leg.display_name or leg.name,
        })

    if (cluster.member_count or 0) > 30:
        lines.append(f"  … e mais {cluster.member_count - 30} deputados.")

    return RetrievalResult(context="\n".join(lines), sources=sources)


async def _general(intent: ClassifyResult, db: AsyncSession) -> RetrievalResult:
    """
    Fallback handler. Provides DB stats plus institutional knowledge about the
    Brazilian legislative process, so Farol can answer conceptual questions
    (urgency regime, party discipline, etc.) without DB data.
    """
    leg_count = (await db.execute(select(func.count()).select_from(Legislator))).scalar_one()
    bill_count = (await db.execute(select(func.count()).select_from(Bill))).scalar_one()
    vote_count = (await db.execute(select(func.count()).select_from(Vote))).scalar_one()

    # Query for bills currently under urgency regime
    urgency_bills = (
        await db.execute(
            select(Bill)
            .where(Bill.urgency_regime == True)  # noqa: E712
            .order_by(Bill.updated_at.desc().nullslast())
            .limit(5)
        )
    ).scalars().all()

    urgency_lines = ""
    urgency_sources: list[dict] = []
    if urgency_bills:
        urgency_lines = "\nProjetos atualmente em regime de urgência:\n" + "\n".join(
            f"  • {b.type} {b.number}/{b.year}: {b.title[:80]}"
            for b in urgency_bills
        )
        urgency_sources = [
            {"type": SOURCE_BILL, "id": str(b.id), "label": f"{b.type} {b.number}/{b.year}"}
            for b in urgency_bills
        ]

    context = f"""\
Base de dados Vigília:
- {leg_count} legisladores cadastrados
- {bill_count} projetos de lei
- {vote_count} votos registrados
{urgency_lines}

Glossário do processo legislativo brasileiro (use para responder perguntas conceituais):

REGIME DE URGÊNCIA: Mecanismo que permite que um projeto de lei seja votado sem passar \
pelas comissões temáticas habituais, reduzindo o prazo de tramitação de meses para dias. \
É aprovado pelo plenário por maioria simples. Usado para matérias consideradas urgentes pelo \
governo ou pela maioria. Crítica frequente: pode reduzir o debate e análise técnica dos projetos.

DISCIPLINA PARTIDÁRIA: Mede o quanto um deputado vota de acordo com a orientação do seu partido. \
Score 1.0 = vota sempre com o partido; score 0.0 = vota sempre contra. \
No Brasil, é comum deputados de partidos do "Centrão" terem disciplina baixa.

CENTRÃO: Bloco informal de partidos brasileiros sem ideologia fixa que apoiam o governo em troca \
de cargos e emendas. Na Vigília, agrupamos deputados por comportamento real de voto, não por partido.

VOTAÇÃO SECRETA: Usada para eleição de membros de órgãos como o TCU. Proibida para leis \
por força da EC 76/2013, que aboliu o voto secreto em votações legislativas.

EMENDA CONSTITUCIONAL (PEC): Proposta que altera a Constituição Federal. Exige aprovação \
em dois turnos, com 3/5 dos votos em cada Casa. Não pode abolir cláusulas pétreas.

MEDIDA PROVISÓRIA (MPV): Ato do Executivo com força de lei imediata, válida por 60 dias \
(prorrogável por mais 60). Precisa ser aprovada pelo Congresso para se tornar lei permanente.\
"""

    return RetrievalResult(context=context, sources=urgency_sources)


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _fmt_score(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "não calculado"


def _fmt_pct(v: float | None) -> str:
    return f"{v * 100:.1f}%" if v is not None else "não calculado"
