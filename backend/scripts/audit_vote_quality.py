"""
Vote-quality audit for high-profile bills.

For each bill in HIGH_PROFILE_BILL_CAMARA_IDS:
  1. Pull all voting sessions from Câmara: /proposicoes/{id}/votacoes
  2. Parse "Sim: X; não: Y; abstenção: Z" from each session's descricao
  3. Classify each session: principal | destaque | emenda | turno | procedural | outro
  4. Pick the session that best represents "the bill itself" (principal vote)
  5. Compare our stored aggregate vs Câmara's principal-session counts
  6. Flag MISLEADING when DB nao > sim but the bill's status says it became law

Outputs:
  - Pretty table to stdout
  - CSV at scripts/output/vote_quality_audit.csv

Usage:
  cd backend && python -m scripts.audit_vote_quality
"""
from __future__ import annotations

import asyncio
import csv
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import dotenv_values

from app.ingestion.camara_client import CamaraClient
from app.ingestion.sync_pipeline import HIGH_PROFILE_BILL_CAMARA_IDS

cfg = dotenv_values(".env")
SUPABASE_URL = cfg["SUPABASE_URL"].rstrip("/")
SERVICE_ROLE_KEY = cfg.get("SUPABASE_SERVICE_ROLE_KEY", "")
if not SERVICE_ROLE_KEY:
    print("SUPABASE_SERVICE_ROLE_KEY missing from .env", file=sys.stderr)
    sys.exit(1)
REST_HEADERS = {
    "apikey": SERVICE_ROLE_KEY,
    "Authorization": f"Bearer {SERVICE_ROLE_KEY}",
}

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("audit")

OUTPUT_CSV = Path(__file__).parent / "output" / "vote_quality_audit.csv"

# ── Parsing ────────────────────────────────────────────────────────────────

# Captures "Sim: 307", "não: 166", "abstenção: 5" (case-insensitive, accent-tolerant).
_COUNT_RE = re.compile(
    r"(sim|n[aã]o|absten[cç][aã]o)\s*[:=]\s*(\d+)",
    re.IGNORECASE,
)


def parse_counts(descricao: str | None) -> tuple[int, int, int] | None:
    """Return (sim, nao, abstencao) parsed from session descricao, or None."""
    if not descricao:
        return None
    found: dict[str, int] = {}
    for m in _COUNT_RE.finditer(descricao):
        key = m.group(1).lower()
        # Normalize accents for the key
        if key.startswith("n"):
            found["nao"] = int(m.group(2))
        elif key.startswith("a"):
            found["abst"] = int(m.group(2))
        else:
            found["sim"] = int(m.group(2))
    if "sim" not in found and "nao" not in found:
        return None
    return found.get("sim", 0), found.get("nao", 0), found.get("abst", 0)


# Re-export the ingester's classifier so the audit and the pipeline can never
# disagree on what counts as a principal session.
from app.ingestion.camara_client import classify_session  # noqa: E402


def has_multi_turn_marker(descs: list[str]) -> bool:
    return any(
        "1º turno" in (d or "").lower()
        or "2º turno" in (d or "").lower()
        or "1o turno" in (d or "").lower()
        or "2o turno" in (d or "").lower()
        or "primeiro turno" in (d or "").lower()
        or "segundo turno" in (d or "").lower()
        for d in descs
    )


# ── Audit ──────────────────────────────────────────────────────────────────

@dataclass
class BillRow:
    camara_id: int
    label: str          # "PEC 45/2019"
    status: str
    our_sim: int
    our_nao: int
    api_sim: int | None
    api_nao: int | None
    session_type: str   # principal | destaque | turno | none
    n_sessions: int
    multi_turn: bool
    match_status: str   # match | mismatch | no-principal | no-api-data | no-db-votes
    action_needed: str

    def as_csv_row(self) -> list:
        return [
            self.label,
            self.our_sim,
            self.our_nao,
            "" if self.api_sim is None else self.api_sim,
            "" if self.api_nao is None else self.api_nao,
            self.session_type,
            self.match_status,
            self.action_needed,
        ]


async def _rest_count(rest: httpx.AsyncClient, table: str, filters: str) -> int:
    """Use PostgREST HEAD + Prefer: count=exact to get a row count."""
    r = await rest.head(
        f"{SUPABASE_URL}/rest/v1/{table}?{filters}",
        headers={**REST_HEADERS, "Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"},
        timeout=20,
    )
    r.raise_for_status()
    cr = r.headers.get("content-range", "")  # "0-0/12345" or "*/12345"
    if "/" in cr:
        try:
            return int(cr.split("/")[1])
        except ValueError:
            pass
    return 0


async def fetch_db_counts(rest: httpx.AsyncClient, camara_id: int) -> tuple[dict | None, dict[str, int]]:
    """Return (bill_dict, {vote_value: count}) for stored votes."""
    r = await rest.get(
        f"{SUPABASE_URL}/rest/v1/bills?camara_id=eq.{camara_id}"
        f"&select=id,type,number,year,status",
        headers=REST_HEADERS, timeout=20,
    )
    r.raise_for_status()
    bills = r.json()
    if not bills:
        return None, {}
    bill = bills[0]
    bill_id = bill["id"]
    sim = await _rest_count(rest, "votes", f"bill_id=eq.{bill_id}&vote_value=eq.sim&select=id")
    # PostgREST URL-encoding for "não": Postgres value contains a non-ASCII char.
    nao = await _rest_count(rest, "votes", f"bill_id=eq.{bill_id}&vote_value=eq.n%C3%A3o&select=id")
    return bill, {"sim": sim, "não": nao}


def pick_principal_session(sessions: list[dict]) -> dict | None:
    """
    Choose the session that best represents the bill's own approval.
    Prefer (in order):
      1. classified=principal AND aprovacao==1 with countable votes
      2. classified=principal with countable votes
      3. aprovacao==1 with countable votes
      4. any session with countable votes (most recent first — the list is
         already date-DESC from the API)
    """
    classified = [(s, classify_session(s.get("descricao"))) for s in sessions]
    countable = [(s, t) for s, t in classified if parse_counts(s.get("descricao"))]
    if not countable:
        return None
    for s, t in countable:
        if t == "principal" and s.get("aprovacao") == 1:
            return s
    for s, t in countable:
        if t == "principal":
            return s
    for s, t in countable:
        if s.get("aprovacao") == 1:
            return s
    return countable[0][0]


def status_outcome(status: str | None) -> str:
    if not status:
        return "pending"
    s = status.lower()
    if any(k in s for k in ("transformad", "promulgad", "sancionad", "convertid")):
        return "approved"
    if "aprovad" in s:
        return "approved"
    if "rejeit" in s or "arquivad" in s:
        return "rejected"
    return "pending"


async def audit_bill(client: CamaraClient, rest: httpx.AsyncClient, camara_id: int) -> BillRow:
    bill, counts = await fetch_db_counts(rest, camara_id)
    if not bill:
        return BillRow(
            camara_id=camara_id,
            label=f"camara_id={camara_id}",
            status="(não no DB)",
            our_sim=0, our_nao=0,
            api_sim=None, api_nao=None,
            session_type="none", n_sessions=0, multi_turn=False,
            match_status="no-db-votes",
            action_needed="Importar bill via sync_pipeline",
        )

    label = f"{bill['type']} {bill['number']}/{bill['year']}"
    bill_status = bill.get("status") or ""
    our_sim = counts.get("sim", 0)
    our_nao = counts.get("não", 0)

    # Pull sessions from Câmara
    try:
        data = await client._get(f"/proposicoes/{camara_id}/votacoes")
    except Exception as e:
        logger.warning("api fail %s: %s", label, e)
        return BillRow(
            camara_id=camara_id, label=label, status=bill_status or "",
            our_sim=our_sim, our_nao=our_nao,
            api_sim=None, api_nao=None,
            session_type="none", n_sessions=0, multi_turn=False,
            match_status="no-api-data",
            action_needed=f"API error: {e}",
        )

    sessions = data.get("dados", []) or []
    descs = [s.get("descricao") for s in sessions]
    multi_turn = has_multi_turn_marker(descs)

    if not sessions:
        return BillRow(
            camara_id=camara_id, label=label, status=bill_status or "",
            our_sim=our_sim, our_nao=our_nao,
            api_sim=None, api_nao=None,
            session_type="none", n_sessions=0, multi_turn=False,
            match_status="no-api-data",
            action_needed=("Câmara não retorna votações para esta proposição. "
                          "Verificar se votação foi simbólica ou via substitutivo."),
        )

    principal = pick_principal_session(sessions)
    if not principal:
        return BillRow(
            camara_id=camara_id, label=label, status=bill_status or "",
            our_sim=our_sim, our_nao=our_nao,
            api_sim=None, api_nao=None,
            session_type="none", n_sessions=len(sessions), multi_turn=multi_turn,
            match_status="no-principal",
            action_needed=("Nenhuma sessão tem placar Sim/Não parseável. "
                          "Verificar manualmente as sessões."),
        )

    session_type = classify_session(principal.get("descricao"))
    api_counts = parse_counts(principal.get("descricao")) or (0, 0, 0)
    api_sim, api_nao, _ = api_counts

    # Tolerance: ±2 for rounding/abstention reclassification edge cases
    sim_off = abs(our_sim - api_sim)
    nao_off = abs(our_nao - api_nao)
    in_tolerance = sim_off <= 2 and nao_off <= 2

    outcome = status_outcome(bill_status)
    db_nao_dominant = our_nao > our_sim
    misleading = outcome == "approved" and db_nao_dominant

    if misleading and session_type != "principal":
        match_status = "MISLEADING"
        action_needed = (
            f"DB mostra {our_sim} sim / {our_nao} não, mas status é "
            f"'{bill_status}'. Sessão ingerida é '{session_type}'. "
            "Re-ingerir somente sessões principais."
        )
    elif misleading:
        match_status = "MISLEADING-multiturn"
        action_needed = (
            "Multi-turno: o último voto por deputado venceu (constraint "
            "uq_vote_legislator_bill). Aceitar ou armazenar todos os turnos."
        )
    elif in_tolerance:
        match_status = "match"
        action_needed = ""
    else:
        match_status = "mismatch"
        action_needed = (
            f"DB ({our_sim}/{our_nao}) ≠ API principal ({api_sim}/{api_nao}). "
            "Reingerir esta proposição."
        )

    return BillRow(
        camara_id=camara_id,
        label=label,
        status=bill_status or "",
        our_sim=our_sim, our_nao=our_nao,
        api_sim=api_sim, api_nao=api_nao,
        session_type=session_type,
        n_sessions=len(sessions),
        multi_turn=multi_turn,
        match_status=match_status,
        action_needed=action_needed,
    )


async def main() -> int:
    rows: list[BillRow] = []
    async with CamaraClient() as client, httpx.AsyncClient() as rest:
        for cid in HIGH_PROFILE_BILL_CAMARA_IDS:
            try:
                row = await audit_bill(client, rest, cid)
            except Exception as e:
                logger.exception("audit failure for %s: %s", cid, e)
                row = BillRow(
                    camara_id=cid, label=f"camara_id={cid}", status="",
                    our_sim=0, our_nao=0, api_sim=None, api_nao=None,
                    session_type="none", n_sessions=0, multi_turn=False,
                    match_status="error", action_needed=str(e),
                )
            rows.append(row)
            print(f"  {row.label:<22}  "
                  f"db={row.our_sim:>3}/{row.our_nao:>3}  "
                  f"api={('-' if row.api_sim is None else row.api_sim):>3}/"
                  f"{('-' if row.api_nao is None else row.api_nao):>3}  "
                  f"{row.session_type:<10} {row.match_status}")

    # CSV
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "bill", "our_sim", "our_nao", "api_sim", "api_nao",
            "session_type", "match_status", "action_needed",
        ])
        for r in rows:
            w.writerow(r.as_csv_row())

    # Summary
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.match_status] = by_status.get(r.match_status, 0) + 1
    print("\n── Resumo ──")
    for k, v in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {k:<22} {v}")
    print(f"\nCSV: {OUTPUT_CSV}")

    # Non-zero exit if anything looks bad — useful for CI later
    bad = sum(v for k, v in by_status.items()
              if k not in ("match", "MISLEADING-multiturn"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
