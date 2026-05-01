"""
TSE donation ingestion pipeline.

Downloads the bulk 2022 candidate accounts ZIP from cdn.tse.jus.br,
filters to deputados federais, cross-references our legislators table
by SHA-256 CPF hash, and upserts donors + donor_links.

Entry point:
  - sync_donors() — full pipeline run
"""
import asyncio
import hashlib
import logging
import os
import re
import tempfile
import zipfile
from io import TextIOWrapper

import httpx
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.models import Donor, DonorLink, Legislator

logger = logging.getLogger(__name__)

# Default URL — can be overridden if TSE moves the file.
DEFAULT_TSE_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/"
    "prestacao_de_contas_eleitorais_candidatos_2022.zip"
)
ELECTION_YEAR = 2022
CARGO_TARGET = "DEPUTADO FEDERAL"

# TSE column names vary by year; we resolve them defensively at parse time.
# Map of canonical_name -> list of TSE header candidates (case-insensitive).
COLUMN_ALIASES = {
    "cargo":          ["DS_CARGO", "DESC_CARGO"],
    "candidate_cpf":  ["NR_CPF_CANDIDATO", "CPF_CANDIDATO"],
    "candidate_name": ["NM_CANDIDATO", "NOME_CANDIDATO"],
    "donor_doc":      ["NR_CPF_CNPJ_DOADOR", "CPF_CNPJ_DOADOR",
                       "NR_CPF_CNPJ_DOADOR_ORIGINARIO"],
    "donor_name":     ["NM_DOADOR", "NOME_DOADOR",
                       "NM_DOADOR_RFB", "NOME_DOADOR_RFB"],
    # CNAE — 2022 schema. Both code (CD_) and description (DS_) flavors.
    "cnae_code":      ["CD_CNAE_DOADOR", "CD_CNAE_DOADOR_ORIGINARIO",
                       "CD_CNAE_ATIVIDADE_PRINCIPAL"],
    "cnae_desc":      ["DS_CNAE_DOADOR", "DS_CNAE_DOADOR_ORIGINARIO",
                       "NM_CNAE_ATIVIDADE_PRINCIPAL",
                       # legacy / unlikely fallbacks
                       "DS_ECONOMICO_DOADOR", "DS_SETOR_ECONOMICO_DOADOR",
                       "SETOR_ECONOMICO_DOADOR"],
    "amount":         ["VR_RECEITA", "VALOR_RECEITA"],
    "source":         ["DS_FONTE_RECURSO", "FONTE_RECURSO"],
    "origem":         ["DS_ORIGEM_RECURSO", "ORIGEM_RECURSO"],
    "natureza":       ["DS_NATUREZA_RECEITA", "NATUREZA_RECEITA"],
    "tipo_doador":    ["NM_TIPO_DOADOR", "DS_TIPO_DOADOR_ORIGINARIO"],
    "donation_type":  ["DS_ORIGEM_RECURSO", "ORIGEM_RECURSO",
                       "DS_NATUREZA_RECEITA"],
    "state_uf":       ["SG_UF", "SG_UE"],
}

# Browser-ish headers — TSE's CDN occasionally returns 403 Forbidden for
# default httpx UAs but lets through realistic browser fingerprints. Even
# when the 403 is IP-based rather than UA-based, the retry-with-delay below
# often succeeds because the block tends to be a sliding-window rate limit.
_TSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "application/zip,application/octet-stream,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


async def _stream_tse_zip(url: str, dest_path: str) -> int:
    """
    Download a TSE bulk zip to dest_path with browser-like headers + a
    light retry-on-403 strategy. Returns the number of bytes written.

    Raises httpx.HTTPStatusError on a non-recoverable failure.
    """
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(
                timeout=600.0,
                follow_redirects=True,
                headers=_TSE_HEADERS,
            ) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    bytes_done = 0
                    with open(dest_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=1 << 20):
                            f.write(chunk)
                            bytes_done += len(chunk)
                    return bytes_done
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code
            if status in (403, 429, 503):
                wait = 30 * attempt  # 30s, 60s, 90s
                logger.warning(
                    "TSE download attempt %d hit %d; sleeping %ds before retry",
                    attempt, status, wait,
                )
                await asyncio.sleep(wait)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("TSE download failed after retries with no recorded exception")


# CNAE 2-digit prefix → our sector slug.
# CNAE 2.0 reference: divisões da Classificação Nacional de Atividades Econômicas.
CNAE2_SECTOR: dict[str, str] = {
    "01": "agronegocio",         # Agricultura, pecuária e serviços
    "02": "agronegocio",         # Produção florestal
    "03": "agronegocio",         # Pesca e aquicultura
    "05": "energia-mineracao",   # Extração de carvão
    "06": "energia-mineracao",   # Extração de petróleo e gás
    "07": "energia-mineracao",   # Extração de minerais metálicos
    "08": "energia-mineracao",   # Extração de minerais não metálicos
    "09": "energia-mineracao",   # Atividades de apoio à extração
    "10": "agronegocio",         # Fabricação de produtos alimentícios
    "11": "agronegocio",         # Fabricação de bebidas
    "12": "agronegocio",         # Fabricação de produtos do fumo
    "19": "energia-mineracao",   # Coque, derivados de petróleo
    "20": "agronegocio",         # Produtos químicos (inclui agroquímicos)
    "35": "energia-mineracao",   # Eletricidade, gás
    "36": "energia-mineracao",   # Captação, tratamento de água
    "37": "energia-mineracao",   # Esgoto
    "38": "energia-mineracao",   # Coleta, tratamento de resíduos
    "39": "energia-mineracao",   # Descontaminação
    "41": "construtoras",        # Construção de edifícios
    "42": "construtoras",        # Obras de infraestrutura
    "43": "construtoras",        # Serviços especializados de construção
    "58": "midia",               # Edição
    "59": "midia",               # Atividades cinematográficas
    "60": "midia",               # Rádio e televisão
    "61": "midia",               # Telecomunicações
    "62": "midia",               # Tecnologia da informação
    "63": "midia",               # Serviços de informação
    "64": "financeiro",          # Atividades de serviços financeiros
    "65": "financeiro",          # Seguros e previdência
    "66": "financeiro",          # Atividades auxiliares dos serviços financeiros
    "85": "educacao",            # Educação
    "86": "saude",               # Atividades de atenção à saúde humana
    "87": "saude",               # Atendimento residencial saúde
    "88": "saude",               # Serviços de assistência social sem alojamento
}

# Specific CNAE codes (4-digit class) that override 2-digit defaults.
# 9491 = Atividades de organizações religiosas (the only reliable religious code).
CNAE_CLASS_OVERRIDE: dict[str, str] = {
    "9491": "religioso",
}

# Map TSE sector text → our slug. Order matters (first match wins).
SECTOR_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(
        r"agric|pecu[áa]r|agro|silvicult|cana[- ]de[- ]a|frigor|"
        r"cultivo|lavoura|criação|criacao|abate|laticín|laticin",
        re.I,
    ), "agronegocio"),
    (re.compile(r"financ|banc|seguro|investiment|cr[ée]dito", re.I),
     "financeiro"),
    (re.compile(r"constru[çc][ãa]o|engenharia civ|imobili[áa]r|incorpora", re.I),
     "construtoras"),
    (re.compile(r"religi|igreja|templo|evangel|cat[óo]l", re.I),
     "religioso"),
    (re.compile(r"sa[úu]de|hospital|m[ée]dic|farmac|laborat[óo]r", re.I),
     "saude"),
    (re.compile(r"ensino|educa[çc][ãa]o|universidade|escola", re.I),
     "educacao"),
    (re.compile(r"telecom|m[íi]dia|comunica[çc][ãa]o|jornal|tv|r[áa]dio", re.I),
     "midia"),
    (re.compile(r"minera|petr[óo]le|extração|combust[íi]vel|energia", re.I),
     "energia-mineracao"),
]


def _hash_doc(doc: str) -> str | None:
    """SHA-256 of stripped digits — must match camara_client._hash_cpf recipe."""
    if not doc:
        return None
    clean = re.sub(r"\D", "", str(doc))
    return hashlib.sha256(clean.encode()).hexdigest() if clean else None


def _normalize_cnae(raw: str | None) -> str | None:
    """Strip non-digits from a CNAE field, return None if no digits remain.

    TSE files commonly use either '0111-0/01' (formatted) or 1110301 (numeric);
    we want just the leading digits to do prefix matching.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    return digits or None


def _classify_by_cnae(cnae: str | None) -> str | None:
    """
    Map a CNAE code to a sector slug. Returns None when the code doesn't
    match any known mapping (so the caller can fall through to text-pattern
    or origem-receita logic).
    """
    digits = _normalize_cnae(cnae)
    if not digits or len(digits) < 2:
        return None
    # 4-digit class override takes precedence (catches 9491 = religious)
    if len(digits) >= 4 and digits[:4] in CNAE_CLASS_OVERRIDE:
        return CNAE_CLASS_OVERRIDE[digits[:4]]
    return CNAE2_SECTOR.get(digits[:2])


_FUNDO_PUBLICO_RE = re.compile(
    r"fundo\s+(especial|eleitoral|partid[áa]rio)",
    re.IGNORECASE,
)


def _classify_sector(
    sector_text: str | None,
    cnae_code: str | None = None,
    cnae_desc: str | None = None,
    origem_recurso: str | None = None,
    natureza: str | None = None,
) -> str:
    """
    Multi-signal classifier (priority order):
      1. DS_ORIGEM_RECURSO / DS_NATUREZA_RECEITA mentioning Fundo Especial /
         Eleitoral / Partidário → 'fundo_publico'.
      2. CNAE code prefix → sector via CNAE2_SECTOR map (with class override).
      3. CNAE description text → SECTOR_PATTERNS regex (semantic fallback).
      4. Legacy free-text sector field → SECTOR_PATTERNS.
      5. 'outros' as last resort.
    """
    # 1. Public-fund signal — overrides any sector guess. The donor here is
    # functionally the public treasury, not a private actor.
    for src in (origem_recurso, natureza):
        if src and _FUNDO_PUBLICO_RE.search(src):
            return "fundo_publico"

    # 2. CNAE code (most reliable when present)
    by_code = _classify_by_cnae(cnae_code)
    if by_code:
        return by_code

    # 3. CNAE description as text
    if cnae_desc:
        for pattern, slug in SECTOR_PATTERNS:
            if pattern.search(cnae_desc):
                return slug

    # 4. Legacy free-text sector field (kept for backward compatibility)
    if sector_text:
        for pattern, slug in SECTOR_PATTERNS:
            if pattern.search(sector_text):
                return slug

    return "outros"


def _entity_type_from_doc(doc: str) -> str | None:
    """Classify by digit count: 11=CPF (PF), 14=CNPJ (PJ)."""
    digits = re.sub(r"\D", "", str(doc or ""))
    if len(digits) == 11:
        return "pessoa_fisica"
    if len(digits) == 14:
        return "pessoa_juridica"
    return None


def _resolve_columns(header: list[str]) -> dict[str, str]:
    """
    Given the actual CSV header, return a mapping of our canonical names
    -> the actual column name in this file. Skips canonicals with no match.
    """
    upper_to_actual = {h.upper(): h for h in header}
    resolved: dict[str, str] = {}
    for canonical, candidates in COLUMN_ALIASES.items():
        for cand in candidates:
            if cand.upper() in upper_to_actual:
                resolved[canonical] = upper_to_actual[cand.upper()]
                break
    return resolved


async def _build_legislator_lookup() -> dict[str, str]:
    """Map cpf_hash -> legislator.id (str) for all known legislators."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Legislator.id, Legislator.cpf_hash)
                .where(Legislator.cpf_hash.is_not(None))
            )
        ).all()
    return {r.cpf_hash: str(r.id) for r in rows}


async def _flush_donors(donors_buf: dict[str, dict]) -> None:
    """Upsert one batch of donors keyed by cnpj_cpf_hash."""
    if not donors_buf:
        return
    async with AsyncSessionLocal() as db:
        stmt = pg_insert(Donor).values(list(donors_buf.values()))
        stmt = stmt.on_conflict_do_update(
            index_elements=["cnpj_cpf_hash"],
            set_={
                "name": stmt.excluded.name,
                "entity_type": stmt.excluded.entity_type,
                "sector_cnae": stmt.excluded.sector_cnae,
                "sector_group": stmt.excluded.sector_group,
                "state_uf": stmt.excluded.state_uf,
            },
        )
        await db.execute(stmt)
        await db.commit()


async def _flush_links(links_agg: dict[tuple, dict]) -> None:
    """
    Resolve donor hashes → ids, then upsert donor_links in chunks.

    Aggregation happens once at end of CSV so per-row sums are correct.
    Each chunk uses ON CONFLICT to upsert idempotently (re-runs of the
    pipeline overwrite, since the in-memory agg already represents the
    full sum for that combination).
    """
    if not links_agg:
        return

    hashes = {key[1] for key in links_agg.keys()}  # key = (leg_id, hash, year, type)
    async with AsyncSessionLocal() as db:
        donor_rows = (
            await db.execute(
                select(Donor.id, Donor.cnpj_cpf_hash)
                .where(Donor.cnpj_cpf_hash.in_(hashes))
            )
        ).all()
        hash_to_id = {r.cnpj_cpf_hash: r.id for r in donor_rows}

        # Build final values list with resolved donor_ids, dropping links
        # whose donor never made it to the donors table.
        values: list[dict] = []
        for (leg_id, donor_hash, year, dtype), payload in links_agg.items():
            did = hash_to_id.get(donor_hash)
            if not did:
                continue
            values.append({
                "legislator_id": leg_id,
                "donor_id": did,
                "amount_brl": payload["amount_brl"],
                "election_year": year,
                "donation_type": dtype,
                "source_doc_ref": payload["source_doc_ref"],
            })

        # Insert in chunks to keep statement size reasonable
        CHUNK = 500
        for i in range(0, len(values), CHUNK):
            chunk = values[i : i + CHUNK]
            stmt = pg_insert(DonorLink).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "legislator_id", "donor_id",
                    "election_year", "donation_type",
                ],
                set_={
                    "amount_brl": stmt.excluded.amount_brl,
                    "source_doc_ref": stmt.excluded.source_doc_ref,
                },
            )
            await db.execute(stmt)
        await db.commit()


async def _process_csv_stream(
    csv_file,
    cols: dict[str, str],
    leg_lookup: dict[str, str],
) -> tuple[int, int]:
    """
    Stream-process a single CSV file.
    Returns (rows_matched, donations_inserted).
    """
    rows_matched = 0
    donations_seen = 0

    # Donors flush periodically (can be 100k+ unique across all candidates).
    # Links AGGREGATE across the whole CSV — sum amounts per
    # (leg, donor_hash, year, type) — then flush once at end.
    DONOR_FLUSH = 1000
    donors_buf: dict[str, dict] = {}
    links_agg: dict[tuple, dict] = {}

    # pandas chunked read keeps memory bounded
    reader = pd.read_csv(
        csv_file,
        sep=";",
        encoding="latin-1",
        chunksize=10_000,
        low_memory=False,
        on_bad_lines="skip",
        dtype=str,  # everything as str; we coerce per field
    )

    for chunk in reader:
        # Filter to deputados federais
        cargo_col = cols.get("cargo")
        if cargo_col and cargo_col in chunk.columns:
            chunk = chunk[chunk[cargo_col].str.upper().str.strip() == CARGO_TARGET]
        if chunk.empty:
            continue

        for _, row in chunk.iterrows():
            donations_seen += 1

            cand_cpf = row.get(cols.get("candidate_cpf", ""), "")
            cand_hash = _hash_doc(cand_cpf)
            leg_id = leg_lookup.get(cand_hash) if cand_hash else None
            if not leg_id:
                continue  # candidate isn't a current deputy in our DB

            donor_doc = row.get(cols.get("donor_doc", ""), "")
            donor_hash = _hash_doc(donor_doc)
            if not donor_hash:
                continue

            # Parse amount: TSE uses comma decimal, sometimes with thousands sep
            amount_raw = str(row.get(cols.get("amount", ""), "0")).replace(".", "").replace(",", ".")
            try:
                amount = float(amount_raw)
            except ValueError:
                continue
            if amount <= 0:
                continue

            donor_name = (row.get(cols.get("donor_name", ""), "") or "").strip()[:300] or "(sem nome)"
            cnae_code = row.get(cols.get("cnae_code", ""), "") if cols.get("cnae_code") else None
            cnae_desc = row.get(cols.get("cnae_desc", ""), "") if cols.get("cnae_desc") else None
            origem    = row.get(cols.get("origem", ""), "")    if cols.get("origem")    else None
            natureza  = row.get(cols.get("natureza", ""), "")  if cols.get("natureza")  else None
            sector_group = _classify_sector(
                sector_text=cnae_desc,
                cnae_code=cnae_code,
                cnae_desc=cnae_desc,
                origem_recurso=origem,
                natureza=natureza,
            )
            sector_cnae = _normalize_cnae(cnae_code)
            entity_type = _entity_type_from_doc(donor_doc)
            state_uf = (row.get(cols.get("state_uf", ""), "") or "").strip()[:2] or None

            donation_type = (row.get(cols.get("donation_type", ""), "") or "").strip()[:50] or "doacao"

            # Dedupe donors within current buffer by hash
            if donor_hash not in donors_buf:
                donors_buf[donor_hash] = {
                    "cnpj_cpf_hash": donor_hash,
                    "name": donor_name,
                    "entity_type": entity_type,
                    "sector_cnae": sector_cnae,
                    "sector_group": sector_group,
                    "state_uf": state_uf,
                }

            # Aggregate links across the whole CSV (sum amounts per key)
            link_key = (leg_id, donor_hash, ELECTION_YEAR, donation_type)
            if link_key in links_agg:
                links_agg[link_key]["amount_brl"] += amount
            else:
                links_agg[link_key] = {
                    "amount_brl": amount,
                    "source_doc_ref": f"TSE2022:{cand_cpf}",
                }

            rows_matched += 1

            # Flush donors periodically; links wait for end-of-CSV
            if len(donors_buf) >= DONOR_FLUSH:
                await _flush_donors(donors_buf)
                donors_buf.clear()

    # Final flush — donors first so the FK target rows exist for links
    await _flush_donors(donors_buf)
    await _flush_links(links_agg)
    return rows_matched, donations_seen


async def inspect_donors_csv(zip_url: str = DEFAULT_TSE_URL) -> None:
    """
    Diagnostic-only: download the TSE zip, read the header line of the
    first receitas CSV, and log all column names + which of our canonical
    aliases resolved. Does not write to the database.
    """
    logger.info("inspect_donors_csv: downloading %s", zip_url)
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "tse.zip")
        await _stream_tse_zip(zip_url, zip_path)
        logger.info("inspect_donors_csv: download done (%d bytes)", os.path.getsize(zip_path))

        with zipfile.ZipFile(zip_path) as zf:
            members = [
                m for m in zf.namelist()
                if re.match(r"receitas_candidatos_2022.*\.csv", m, re.I)
            ]
            if not members:
                logger.warning("inspect_donors_csv: no receitas CSVs found")
                return
            target = sorted(members, key=lambda m: zf.getinfo(m).file_size)[0]
            with zf.open(target) as raw:
                header_line = raw.readline().decode("latin-1")
            cols = [c.strip().strip('"') for c in header_line.split(";")]
            logger.info("inspect_donors_csv: first CSV = %s, %d columns", target, len(cols))
            logger.info("inspect_donors_csv: ALL COLUMNS:")
            for i, c in enumerate(cols):
                logger.info("  [%3d] %s", i, c)
            # Which donor-sector-related columns exist?
            sector_like = [c for c in cols if any(
                k in c.upper() for k in ("SETOR", "CNAE", "ECON", "ATIV")
            )]
            logger.info("inspect_donors_csv: SECTOR-LIKE COLUMNS = %s", sector_like)
            resolved = _resolve_columns(cols)
            logger.info("inspect_donors_csv: RESOLVED ALIASES = %s", resolved)


async def sync_donors(zip_url: str = DEFAULT_TSE_URL) -> None:
    """
    Full pipeline: download TSE zip → process each receitas CSV → upsert
    donors + donor_links for federal deputies in our DB.
    """
    logger.info("sync_donors: starting download from %s", zip_url)
    leg_lookup = await _build_legislator_lookup()
    logger.info("sync_donors: %d legislators with cpf_hash available", len(leg_lookup))

    if not leg_lookup:
        logger.error("sync_donors: no legislators with cpf_hash; abort")
        return

    total_matched = 0
    total_seen = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "tse.zip")

        # Stream download to disk to keep memory bounded
        bytes_done = await _stream_tse_zip(zip_url, zip_path)
        logger.info(
            "sync_donors: download complete (%.1f MB)",
            bytes_done / (1024 * 1024),
        )

        # Iterate CSVs of interest inside the zip without extracting all
        with zipfile.ZipFile(zip_path) as zf:
            target_members = [
                m for m in zf.namelist()
                if re.match(r"receitas_candidatos_2022.*\.csv", m, re.I)
            ]
            logger.info("sync_donors: %d receitas CSVs found in zip", len(target_members))

            for member in target_members:
                logger.info("sync_donors: processing %s", member)
                with zf.open(member) as raw:
                    # Sniff header from first line for column resolution
                    stream = TextIOWrapper(raw, encoding="latin-1", newline="")
                    first_line = stream.readline()
                    header = [h.strip().strip('"') for h in first_line.split(";")]
                    cols = _resolve_columns(header)
                    missing = [k for k in ("cargo", "candidate_cpf", "donor_doc", "amount") if k not in cols]
                    if missing:
                        logger.warning(
                            "sync_donors: %s missing required cols %s — skipping",
                            member, missing,
                        )
                        continue

                # Re-open for actual parse (chunked) — pandas reads from start
                with zf.open(member) as raw2:
                    stream2 = TextIOWrapper(raw2, encoding="latin-1", newline="")
                    matched, seen = await _process_csv_stream(text2, cols, leg_lookup)
                    total_matched += matched
                    total_seen += seen
                    logger.info(
                        "sync_donors: %s done — matched=%d seen=%d",
                        member, matched, seen,
                    )

    logger.info(
        "sync_donors: COMPLETE — total_matched=%d total_seen=%d",
        total_matched, total_seen,
    )


if __name__ == "__main__":
    async def _main():
        logging.basicConfig(level=logging.INFO)
        await sync_donors()

    asyncio.run(_main())


# ────────────────────────────────────────────────────────────────────────────
# Reclassify-only pipeline — refresh sector_cnae + sector_group on existing
# donor rows without touching donor_links or legislator references.
# ────────────────────────────────────────────────────────────────────────────
async def reclassify_donors(zip_url: str = DEFAULT_TSE_URL) -> None:
    """
    Walk the TSE 2022 receitas CSVs again, but only build a
      cnpj_cpf_hash → (cnae_code, sector_group)
    mapping and UPDATE donors.sector_cnae / donors.sector_group.

    This is the fix for the original ingest bug, where COLUMN_ALIASES
    didn't match the real TSE column names so every donor landed at
    sector_group='outros'. Now we use the correct CD_CNAE_DOADOR /
    DS_CNAE_DOADOR columns plus the multi-signal _classify_sector
    helper. donor_links is untouched — only the classification fields
    on existing donor rows change.

    Idempotent: running again with the same TSE data produces the
    same final state.
    """
    logger.info("reclassify_donors: starting download from %s", zip_url)

    # Build the in-memory map first; one source of truth for resolution.
    # Per-donor: prefer the CNAE classification when available; otherwise
    # take whatever signal we have (origem/natureza/text).
    classification: dict[str, tuple[str | None, str]] = {}  # hash -> (cnae_digits, sector_group)

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "tse.zip")
        bytes_done = await _stream_tse_zip(zip_url, zip_path)
        logger.info(
            "reclassify_donors: download complete (%.1f MB)",
            bytes_done / (1024 * 1024),
        )

        with zipfile.ZipFile(zip_path) as zf:
            members = [
                m for m in zf.namelist()
                if re.match(r"receitas_candidatos_2022.*\.csv", m, re.I)
            ]
            logger.info("reclassify_donors: %d receitas CSVs in zip", len(members))

            for member in members:
                # Resolve columns from header
                with zf.open(member) as raw:
                    stream = TextIOWrapper(raw, encoding="latin-1", newline="")
                    first_line = stream.readline()
                    header = [h.strip().strip('"') for h in first_line.split(";")]
                    cols = _resolve_columns(header)
                missing = [k for k in ("cargo", "donor_doc") if k not in cols]
                if missing:
                    logger.warning(
                        "reclassify_donors: %s missing cols %s — skip",
                        member, missing,
                    )
                    continue

                logger.info(
                    "reclassify_donors: %s — cols resolved: cnae_code=%s cnae_desc=%s origem=%s",
                    member,
                    cols.get("cnae_code"),
                    cols.get("cnae_desc"),
                    cols.get("origem"),
                )

                # Stream-process all rows from this CSV
                with zf.open(member) as raw2:
                    stream2 = TextIOWrapper(raw2, encoding="latin-1", newline="")
                    reader = pd.read_csv(
                        stream2,
                        sep=";",
                        encoding="latin-1",
                        chunksize=20_000,
                        low_memory=False,
                        on_bad_lines="skip",
                        dtype=str,
                    )
                    for chunk in reader:
                        cargo_col = cols.get("cargo")
                        if cargo_col and cargo_col in chunk.columns:
                            chunk = chunk[
                                chunk[cargo_col].str.upper().str.strip() == CARGO_TARGET
                            ]
                        if chunk.empty:
                            continue
                        for _, row in chunk.iterrows():
                            donor_doc = row.get(cols.get("donor_doc", ""), "")
                            donor_hash = _hash_doc(donor_doc)
                            if not donor_hash:
                                continue
                            cnae_code = row.get(cols.get("cnae_code", ""), "") if cols.get("cnae_code") else None
                            cnae_desc = row.get(cols.get("cnae_desc", ""), "") if cols.get("cnae_desc") else None
                            origem    = row.get(cols.get("origem",    ""), "") if cols.get("origem")    else None
                            natureza  = row.get(cols.get("natureza",  ""), "") if cols.get("natureza")  else None
                            sector_group = _classify_sector(
                                sector_text=cnae_desc,
                                cnae_code=cnae_code,
                                cnae_desc=cnae_desc,
                                origem_recurso=origem,
                                natureza=natureza,
                            )
                            cnae_digits = _normalize_cnae(cnae_code)
                            # Prefer rows that produced a non-'outros' classification
                            existing = classification.get(donor_hash)
                            if existing is None or (
                                existing[1] == "outros" and sector_group != "outros"
                            ):
                                classification[donor_hash] = (cnae_digits, sector_group)

    logger.info(
        "reclassify_donors: classification map built, %d unique donors with TSE data",
        len(classification),
    )

    # Bulk-apply via UPDATE FROM VALUES, in chunks to keep statements bounded.
    CHUNK = 1000
    items = list(classification.items())
    updated = 0
    async with AsyncSessionLocal() as db:
        for i in range(0, len(items), CHUNK):
            batch = items[i : i + CHUNK]
            # Build a VALUES expression: (hash, cnae, sector)
            values_sql = ", ".join(
                f"(:h{i+j}, :c{i+j}, :s{i+j})" for j in range(len(batch))
            )
            params = {}
            for j, (h, (cnae, sg)) in enumerate(batch):
                params[f"h{i+j}"] = h
                params[f"c{i+j}"] = cnae
                params[f"s{i+j}"] = sg
            sql = text(f"""
                UPDATE donors d
                SET sector_cnae = v.cnae,
                    sector_group = v.sector
                FROM (VALUES {values_sql}) AS v(hash, cnae, sector)
                WHERE d.cnpj_cpf_hash = v.hash
            """)
            result = await db.execute(sql, params)
            updated += result.rowcount or 0
            await db.commit()

    logger.info(
        "reclassify_donors: COMPLETE — %d donor rows updated (of %d in TSE map)",
        updated, len(classification),
    )
