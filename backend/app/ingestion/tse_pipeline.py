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
from sqlalchemy import select
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
    "donor_sector":   ["DS_ECONOMICO_DOADOR", "DS_SETOR_ECONOMICO_DOADOR",
                       "SETOR_ECONOMICO_DOADOR"],
    "amount":         ["VR_RECEITA", "VALOR_RECEITA"],
    "source":         ["DS_FONTE_RECURSO", "FONTE_RECURSO"],
    "donation_type":  ["DS_ORIGEM_RECURSO", "ORIGEM_RECURSO",
                       "DS_NATUREZA_RECEITA"],
    "state_uf":       ["SG_UF", "SG_UE"],
}

# Map TSE sector text → our slug. Order matters (first match wins).
SECTOR_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"agric|pecu[áa]r|agro|silvicult|cana[- ]de[- ]a|frigor", re.I),
     "agronegocio"),
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


def _classify_sector(sector_text: str | None) -> str:
    if not sector_text:
        return "outros"
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


async def _flush_batch(
    donors_buf: dict[str, dict],
    links_buf: list[dict],
) -> None:
    """Upsert one batch of donors then donor_links."""
    if not donors_buf and not links_buf:
        return

    async with AsyncSessionLocal() as db:
        # 1. Upsert donors keyed by cnpj_cpf_hash
        if donors_buf:
            stmt = pg_insert(Donor).values(list(donors_buf.values()))
            stmt = stmt.on_conflict_do_update(
                index_elements=["cnpj_cpf_hash"],
                set_={
                    "name": stmt.excluded.name,
                    "entity_type": stmt.excluded.entity_type,
                    "sector_group": stmt.excluded.sector_group,
                    "state_uf": stmt.excluded.state_uf,
                },
            )
            await db.execute(stmt)
            await db.flush()

        # 2. Resolve donor_id for each link via the just-upserted hashes
        if links_buf:
            hashes = {l["_donor_hash"] for l in links_buf}
            donor_rows = (
                await db.execute(
                    select(Donor.id, Donor.cnpj_cpf_hash)
                    .where(Donor.cnpj_cpf_hash.in_(hashes))
                )
            ).all()
            hash_to_id = {r.cnpj_cpf_hash: r.id for r in donor_rows}

            link_values = []
            for l in links_buf:
                did = hash_to_id.get(l["_donor_hash"])
                if not did:
                    continue
                link_values.append({
                    "legislator_id": l["legislator_id"],
                    "donor_id": did,
                    "amount_brl": l["amount_brl"],
                    "election_year": l["election_year"],
                    "donation_type": l["donation_type"],
                    "source_doc_ref": l["source_doc_ref"],
                })

            if link_values:
                link_stmt = pg_insert(DonorLink).values(link_values)
                link_stmt = link_stmt.on_conflict_do_update(
                    index_elements=[
                        "legislator_id", "donor_id",
                        "election_year", "donation_type",
                    ],
                    set_={
                        "amount_brl": link_stmt.excluded.amount_brl,
                        "source_doc_ref": link_stmt.excluded.source_doc_ref,
                    },
                )
                await db.execute(link_stmt)

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

    # Buffers — flushed every BATCH_SIZE rows
    BATCH_SIZE = 500
    donors_buf: dict[str, dict] = {}  # hash -> donor row
    links_buf: list[dict] = []

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
            sector_text = row.get(cols.get("donor_sector", ""), "") if cols.get("donor_sector") else ""
            sector_group = _classify_sector(sector_text)
            entity_type = _entity_type_from_doc(donor_doc)
            state_uf = (row.get(cols.get("state_uf", ""), "") or "").strip()[:2] or None

            donation_type = (row.get(cols.get("donation_type", ""), "") or "").strip()[:50] or "doacao"

            # Dedupe donors within batch by hash
            if donor_hash not in donors_buf:
                donors_buf[donor_hash] = {
                    "cnpj_cpf_hash": donor_hash,
                    "name": donor_name,
                    "entity_type": entity_type,
                    "sector_group": sector_group,
                    "state_uf": state_uf,
                }

            links_buf.append({
                "legislator_id": leg_id,
                "_donor_hash": donor_hash,
                "amount_brl": amount,
                "election_year": ELECTION_YEAR,
                "donation_type": donation_type,
                "source_doc_ref": f"TSE2022:{cand_cpf}:{donor_doc}",
            })

            rows_matched += 1

            if len(links_buf) >= BATCH_SIZE:
                await _flush_batch(donors_buf, links_buf)
                donors_buf.clear()
                links_buf.clear()

    # Final flush
    await _flush_batch(donors_buf, links_buf)
    return rows_matched, donations_seen


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
        async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
            async with client.stream("GET", zip_url) as resp:
                resp.raise_for_status()
                bytes_total = int(resp.headers.get("content-length", 0))
                bytes_done = 0
                with open(zip_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=1 << 20):  # 1 MB
                        f.write(chunk)
                        bytes_done += len(chunk)
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
                    text = TextIOWrapper(raw, encoding="latin-1", newline="")
                    first_line = text.readline()
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
                    text2 = TextIOWrapper(raw2, encoding="latin-1", newline="")
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
