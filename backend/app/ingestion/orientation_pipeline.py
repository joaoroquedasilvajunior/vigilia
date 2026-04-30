"""
Orientation backfill — populates votes.party_orientation.

The Câmara per-vote payload (/votacoes/{id}/votos) does NOT include the
party orientation. Orientations come from a separate endpoint
(/votacoes/{id}/orientacoes) that returns one row per *bloc* (sometimes
per single party), with shapes like:

  - "PL"                       → single-party orientation
  - "Bl MdbPsdRepPodePsc"      → multi-party bloc, CamelCase concatenated
  - "Fdr PT-PCdoB-PV"          → federation, dash-separated
  - "Governo" / "Maioria" / ...→ leadership grouping (skip — not party-keyed)

For each (session, party) pair we resolve, we update every vote in that
session belonging to a current member of that party. Limitations:
  * Uses *current* legislator → party mapping (we don't track historical
    party migrations). A deputy who switched parties since the vote will
    be assigned the new party's orientation, not their party-at-time.
    For the 57th legislature this is a small fraction of cases.
  * Skips orientations with no party match (Governo / Maioria / Minoria /
    Oposição) — those are leadership-level and don't translate to a
    specific bancada-level discipline check.

Entry point: sync_party_orientations()
"""
from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import select, text, update

from app.db import AsyncSessionLocal
from app.ingestion.camara_client import CamaraClient
from app.models import Legislator, Party, Session, Vote

logger = logging.getLogger(__name__)

# Bloc names that don't map to a specific bancada — skip
LEADERSHIP_LABELS = {
    "governo", "maioria", "minoria", "oposição", "oposicao",
}


def _split_camel(s: str) -> list[str]:
    """'MdbPsdRepPodePsc' → ['Mdb', 'Psd', 'Rep', 'Pode', 'Psc']."""
    return re.findall(r"[A-Z][a-z]*", s)


def _resolve_parties(sigla: str, party_acronyms: list[str]) -> list[str]:
    """
    Map a Câmara `siglaPartidoBloco` to a list of party acronyms in our DB.
    Returns [] when the label doesn't represent a specific party (e.g. "Governo").
    """
    raw = sigla.strip()
    if not raw:
        return []
    if raw.lower() in LEADERSHIP_LABELS:
        return []

    # Exact party match (single-party leadership: "PL", "NOVO", etc.)
    if raw.upper() in {p.upper() for p in party_acronyms}:
        # Map back to the canonical-cased acronym from DB
        return [p for p in party_acronyms if p.upper() == raw.upper()]

    # Federations: "Fdr PT-PCdoB-PV" → ["PT", "PCdoB", "PV"]
    fdr_match = re.match(r"^Fdr\s+(.+)$", raw, flags=re.I)
    if fdr_match:
        tokens = [t.strip() for t in fdr_match.group(1).split("-") if t.strip()]
        return [
            p for p in party_acronyms
            if any(p.upper() == t.upper() for t in tokens)
        ]

    # Bloco: "Bl MdbPsdRepPodePsc" → split on capitals → prefix-match parties
    bl_match = re.match(r"^Bl\s+(.+)$", raw, flags=re.I)
    if bl_match:
        tokens = [t.upper() for t in _split_camel(bl_match.group(1))]
        matched: list[str] = []
        for tok in tokens:
            for p in party_acronyms:
                if p.upper() == tok or p.upper().startswith(tok):
                    if p not in matched:
                        matched.append(p)
                        break
        return matched

    return []


async def _load_party_lookup(db) -> tuple[dict[str, str], list[str]]:
    """Returns (acronym → party_id_str) and a list of acronyms for matching."""
    rows = (await db.execute(select(Party.id, Party.acronym))).all()
    lookup = {r.acronym: str(r.id) for r in rows}
    return lookup, list(lookup.keys())


async def sync_party_orientations(rate_limit_sleep: float = 0.4) -> None:
    """
    Walk every distinct (session_id, sessions.camara_id) referenced by votes,
    fetch its orientations from Câmara, and UPDATE votes.party_orientation
    for legislators currently affiliated with each matched party.

    Idempotent: re-running just overwrites with the same values.
    """
    logger.info("sync_party_orientations: starting")

    async with AsyncSessionLocal() as db:
        party_id_by_acro, party_acronyms = await _load_party_lookup(db)
        rows = (
            await db.execute(
                select(Session.id, Session.camara_id)
                .where(Session.id.in_(select(Vote.session_id).distinct()))
            )
        ).all()
        sessions_to_process = [(str(r.id), r.camara_id) for r in rows if r.camara_id]

    logger.info(
        "sync_party_orientations: %d sessions, %d known parties",
        len(sessions_to_process), len(party_acronyms),
    )

    processed = 0
    matched_orient_rows = 0
    skipped_orient_rows = 0
    votes_updated = 0

    async with CamaraClient() as client:
        for session_id, camara_id in sessions_to_process:
            try:
                orientations = await client.get_orientations_for_session(camara_id)
            except Exception as exc:
                logger.warning("session %s fetch failed: %s", camara_id, exc)
                continue

            # Pre-aggregate: party_acronym → orientation (party-level wins
            # over bloc-level when the same party appears in both)
            party_orient: dict[str, str] = {}
            party_level_keys: set[str] = set()

            for o in orientations:
                if not o["orientation"]:
                    skipped_orient_rows += 1
                    continue
                resolved = _resolve_parties(o["sigla"], party_acronyms)
                if not resolved:
                    skipped_orient_rows += 1
                    continue
                matched_orient_rows += 1
                if o["tipo"] == "P":
                    # Party-level — overrides any prior bloc-level
                    for acro in resolved:
                        party_orient[acro] = o["orientation"]
                        party_level_keys.add(acro)
                else:
                    # Bloc-level — only set if not already set by a party-level
                    for acro in resolved:
                        if acro not in party_level_keys:
                            party_orient[acro] = o["orientation"]

            if not party_orient:
                processed += 1
                await asyncio.sleep(rate_limit_sleep)
                continue

            # Apply via one UPDATE per party (each touches the votes for its
            # members in this session). Total: ~10 UPDATEs per session.
            async with AsyncSessionLocal() as db:
                for acro, orient in party_orient.items():
                    party_id = party_id_by_acro.get(acro)
                    if not party_id:
                        continue
                    result = await db.execute(
                        update(Vote)
                        .where(Vote.session_id == session_id)
                        .where(
                            Vote.legislator_id.in_(
                                select(Legislator.id).where(
                                    Legislator.nominal_party_id == party_id
                                )
                            )
                        )
                        .values(party_orientation=orient)
                    )
                    votes_updated += result.rowcount or 0
                await db.commit()

            processed += 1
            if processed % 50 == 0:
                logger.info(
                    "sync_party_orientations: %d/%d sessions — "
                    "votes_updated=%d matched_rows=%d skipped_rows=%d",
                    processed, len(sessions_to_process),
                    votes_updated, matched_orient_rows, skipped_orient_rows,
                )

            await asyncio.sleep(rate_limit_sleep)

    logger.info(
        "sync_party_orientations: COMPLETE — sessions=%d votes_updated=%d "
        "matched_rows=%d skipped_rows=%d",
        processed, votes_updated, matched_orient_rows, skipped_orient_rows,
    )


if __name__ == "__main__":
    async def _main() -> None:
        logging.basicConfig(level=logging.INFO)
        await sync_party_orientations()
    asyncio.run(_main())
