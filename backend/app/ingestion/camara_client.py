import asyncio
import hashlib
import re
import time
from datetime import datetime, timedelta
from typing import AsyncGenerator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

BASE_URL = settings.camara_api_base_url


# ── Voting-session classification ─────────────────────────────────────────────
# Câmara returns one bill's `/votacoes` as a flat list of sessions covering the
# texto-base, every destaque, every emenda, sometimes procedural (urgência /
# requerimento) votes. Aggregating across all of them yields a misleading
# "placar" — typically the destaques drown out the principal vote. We classify
# each session by its descricao and prefer principal sessions when available.
#
# Order matters: destaque is checked first because some destaque descriptions
# also mention "projeto" (e.g. "Destaque do PT para suprimir art. 2º do
# projeto") — we never want those to slip into the principal bucket.
# Procedural sessions are votes about *how* to vote, not on the bill itself
# (urgency motions, breaking the interstício between turns, recursos against
# rulings, etc). They commonly mention "segundo turno" inside the requerimento
# text, which is why we need to filter them out *before* checking principal.
_PROCEDURAL_KEYWORDS = (
    "requerimento", "recurso",
    "interstício", "intersticio",
    "questão de ordem", "questao de ordem",
    "urgência (art", "urgencia (art",   # "Aprovado o Requerimento de Urgência"
)

# Destaques and supressive emendas — votes on parts of a text, not the text.
# Bare "emenda" is intentionally NOT here: PEC titles ("Proposta de Emenda à
# Constituição") would false-match. "Subemenda" alone isn't here either —
# "Subemenda Substitutiva Global" is often the principal vote.
_DESTAQUE_KEYWORDS = (
    "supressão", "supressao",
    "mantido o texto",
    "suprimido o texto",
    "emenda supressiva",
    "subemenda supressiva",
    "emenda aglutinativa",        # almost always destaque-style
    "emenda de plenário", "emenda de plenario",
)
# Stricter destaque patterns: bare "destaque" false-matches the standard
# Câmara phrasing "ressalvados os destaques" that appears in *principal*
# vote descriptions. We require destaque to either start the descricao
# or be followed by "para"/"do"/"da" (the natural way of naming a destaque).
_DESTAQUE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"^\s*destaque\b",
        r"\bdestaque\s+(?:para|d[oae]s?|apresentad[oa])\b",
        r"\bvota[cç][aã]o\s+do\s+destaque\b",
    )
)

# Principal patterns — these are the only ways the actual approval of the
# bill itself is phrased in Câmara descricao fields. Strict on purpose.
_PRINCIPAL_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\baprovad[oa]\s+o\s+projeto\b",
        r"\baprovad[oa]\s+a\s+proposta\s+de\s+emenda\b",
        r"\baprovad[oa]\s+o\s+substitutivo\b",
        r"\baprovad[oa]\s+a\s+subemenda\s+substitutiva\b",
        r"\baprovad[oa]\s+a\s+reda[cç][aã]o\s+final\b",
        # "Aprovada, em segundo turno, a Proposta..."
        r"\baprovad[oa],?\s+em\s+(?:primeiro|segundo|1[ºo]|2[ºo])\s+turno\b",
        r"\baprovad[oa]\s+em\s+turno\s+[úu]nico\b",
        # "Aprovado o texto-base" / "Texto-base aprovado"
        r"\btexto[\s\-]base\b",
        r"\baprova[cç][aã]o\s+do\s+projeto\b",
    )
)


def classify_session(descricao: str | None) -> str:
    """
    Classify a Câmara voting session as one of:
      - 'procedural' — requerimento, recurso, interstício
      - 'destaque'   — destaque, mantido/suprimido o texto, emenda supressiva
      - 'principal'  — actual approval of the bill itself
      - 'outro'      — couldn't tell
    Order matters: procedural beats destaque beats principal, because
    procedural descriptions often quote turno phrases ("...para apreciação
    em segundo turno") that would otherwise look principal.
    """
    if not descricao:
        return "outro"
    d = descricao.lower()
    if any(k in d for k in _PROCEDURAL_KEYWORDS):
        return "procedural"
    if any(k in d for k in _DESTAQUE_KEYWORDS) or any(p.search(d) for p in _DESTAQUE_PATTERNS):
        return "destaque"
    if any(p.search(d) for p in _PRINCIPAL_PATTERNS):
        return "principal"
    return "outro"


class CamaraClient:
    """
    Async client for the Câmara dos Deputados open data API (v2).
    Handles pagination, rate limiting, and error recovery.
    """

    def __init__(self, rate_limit_per_sec: float | None = None):
        self.rate_limit_per_sec = rate_limit_per_sec or settings.camara_rate_limit_per_sec
        self._last_request: float = 0.0
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CamaraClient":
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()

    async def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        wait = (1.0 / self.rate_limit_per_sec) - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_request = time.monotonic()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=5, min=5, max=60))
    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        await self._throttle()
        assert self._client is not None, "Use CamaraClient as an async context manager"
        response = await self._client.get(endpoint, params=params or {})
        response.raise_for_status()
        return response.json()

    # ── Public API methods ──────────────────────────────────────────────────

    async def get_legislators(self, legislature: int | None = None) -> AsyncGenerator[dict, None]:
        """Stream all deputies for a given legislature (default: current 57th)."""
        leg = legislature or settings.camara_legislature
        page = 1
        while True:
            data = await self._get("/deputados", params={
                "idLegislatura": leg,
                "itens": 100,
                "pagina": page,
                "ordem": "ASC",
                "ordenarPor": "nome",
            })
            items = data.get("dados", [])
            if not items:
                break
            for item in items:
                yield self._normalize_legislator(item)
            if not any(lnk.get("rel") == "next" for lnk in data.get("links", [])):
                break
            page += 1

    async def get_legislator_detail(self, camara_id: int) -> dict:
        """Full deputy profile including education, declared assets, etc."""
        data = await self._get(f"/deputados/{camara_id}")
        return self._normalize_legislator_detail(data.get("dados", {}))

    async def get_bills(
        self,
        since_date: datetime | None = None,
        bill_types: list[str] | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Stream bills filtered by date and type."""
        if since_date is None:
            since_date = datetime.now() - timedelta(days=30)
        if bill_types is None:
            bill_types = ["PL", "PEC", "MPV"]

        for bill_type in bill_types:
            page = 1
            while True:
                data = await self._get("/proposicoes", params={
                    "siglaTipo": bill_type,
                    "dataApresentacaoInicio": since_date.strftime("%Y-%m-%d"),
                    "itens": 100,
                    "pagina": page,
                })
                items = data.get("dados", [])
                if not items:
                    break
                for item in items:
                    yield self._normalize_bill(item)
                if not any(lnk.get("rel") == "next" for lnk in data.get("links", [])):
                    break
                page += 1

    async def get_voting_sessions(
        self,
        date_start: str,
        date_end: str,
        plenary_only: bool = True,
        chunk_days: int = 90,
    ) -> AsyncGenerator[dict, None]:
        """
        Iterate /votacoes endpoint, yielding voting-session metadata.

        The API rejects multi-year date windows with HTTP 400 (undocumented
        max range), so we chunk the [date_start, date_end] interval into
        windows of `chunk_days` days and paginate within each.

        Plenary-only filter is applied client-side because the API ignores
        siglaOrgao as a query param.

        Yields: {session_id, bill_camara_id, date, sigla_orgao, descricao}.
        """
        import re
        from datetime import datetime, timedelta

        start_dt = datetime.strptime(date_start, "%Y-%m-%d")
        end_dt   = datetime.strptime(date_end,   "%Y-%m-%d")

        # Lazy-import logging to avoid module-init reordering
        import logging as _logging
        _log = _logging.getLogger(__name__)

        win_start = start_dt
        while win_start <= end_dt:
            win_end = min(win_start + timedelta(days=chunk_days - 1), end_dt)
            win_label = f"{win_start.date()}→{win_end.date()}"
            try:
                page = 1
                while True:
                    data = await self._get("/votacoes", params={
                        "dataInicio": win_start.strftime("%Y-%m-%d"),
                        "dataFim":    win_end.strftime("%Y-%m-%d"),
                        "itens":      100,
                        "pagina":     page,
                        "ordem":      "ASC",
                        "ordenarPor": "dataHoraRegistro",
                    })
                    items = data.get("dados", [])
                    if not items:
                        break
                    for s in items:
                        sigla = s.get("siglaOrgao")
                        if plenary_only and sigla != "PLEN":
                            continue
                        # Session id format: {bill_camara_id}-{seq}
                        sess_id = s.get("id") or ""
                        m = re.match(r"^(\d+)-", sess_id)
                        if not m:
                            continue
                        yield {
                            "session_id":      sess_id,
                            "bill_camara_id":  int(m.group(1)),
                            "date":            s.get("data"),
                            "sigla_orgao":     sigla,
                            "descricao":       s.get("descricao") or "",
                        }
                    if not any(lnk.get("rel") == "next" for lnk in data.get("links", [])):
                        break
                    page += 1
            except Exception as exc:
                # 504s, transient network, etc — don't kill the whole walk
                _log.warning(
                    "get_voting_sessions: chunk %s failed (%s); skipping window",
                    win_label, exc,
                )
            win_start = win_end + timedelta(days=1)

    async def get_orientations_for_session(self, session_camara_id: str) -> list[dict]:
        """
        Fetch the per-bloc/per-party voting orientations for a session.

        Returns a list of normalized rows: {sigla, orientation, tipo}, where
        - sigla: bloc/party label as returned by Câmara (e.g. "PL",
          "Bl MdbPsdRepPodePsc", "Fdr PT-PCdoB-PV", "Governo")
        - orientation: normalized to vote-value vocabulary ("sim", "não",
          "obstrucao", "livre"); None for unmapped values like leadership
          orientations the API doesn't translate
        - tipo: "P" (party-level) | "B" (bloc-level)
        """
        data = await self._get(f"/votacoes/{session_camara_id}/orientacoes")
        out: list[dict] = []
        for r in data.get("dados", []):
            out.append({
                "sigla":       (r.get("siglaPartidoBloco") or "").strip(),
                "orientation": self._normalize_orientation(r.get("orientacaoVoto")),
                "tipo":        r.get("codTipoLideranca"),
            })
        return out

    async def get_votes_for_bill(self, camara_bill_id: int) -> list[dict]:
        """
        Fetch all individual votes for a bill.
        One bill may have multiple voting sessions (e.g. committee + plenary).
        """
        sessions_data = await self._get(f"/proposicoes/{camara_bill_id}/votacoes")
        votes: list[dict] = []
        for session in sessions_data.get("dados", []):
            session_votes = await self._get(f"/votacoes/{session['id']}/votos")
            for v in session_votes.get("dados", []):
                votes.append({
                    "legislator_camara_id": v.get("deputado_", {}).get("id"),
                    "vote_value": self._normalize_vote(v.get("tipoVoto")),
                    "party_orientation": self._normalize_orientation(v.get("orientacaoVoto")),
                    "session_camara_id": session["id"],
                    "voted_at": v.get("dataHoraVoto"),
                })
        return votes

    async def get_principal_votes_for_bill(
        self, camara_bill_id: int,
    ) -> tuple[list[dict], dict]:
        """
        Fetch votes from the bill's *principal* voting session only —
        i.e. the texto-base / redação final / single-turn approval —
        skipping destaques, emendas and procedural votes.

        Selection rule:
          1. Pick the most recent session classified as 'principal'
             (Câmara returns sessions in date-DESC order, so the first
             principal in the list is the final approval).
          2. If no principal exists, fall back to the session with the
             most individual votes recorded (proxy for "the one most
             deputies showed up to").

        Returns (votes, meta) where meta describes which session was
        chosen and why — useful for logging / audits.
        """
        sessions_data = await self._get(f"/proposicoes/{camara_bill_id}/votacoes")
        sessions = sessions_data.get("dados", []) or []
        if not sessions:
            return [], {
                "chosen_session_id": None, "reason": "no-sessions",
                "n_sessions": 0, "n_principal": 0,
            }

        classified = [(s, classify_session(s.get("descricao"))) for s in sessions]
        principals = [s for s, t in classified if t == "principal"]

        chosen: dict | None = None
        chosen_rows: list[dict] = []
        reason: str = ""

        # First pass: walk principals (date-DESC → most-recent first) and pick
        # the first one that actually has roll-call votes. "Redação Final"
        # sessions are often by acclamation and have 0 individual votes — we
        # need to keep walking back to the substantive turno vote.
        for cand in principals:
            sv = await self._get(f"/votacoes/{cand['id']}/votos")
            rows = sv.get("dados", []) or []
            if rows:
                chosen, chosen_rows, reason = cand, rows, "principal"
                break

        # No principal had roll-call votes → pick the session with the most
        # individual votes recorded. Ignores destaques only if a non-destaque
        # candidate exists with at least as many votes.
        if not chosen:
            best_n = -1
            best: dict | None = None
            best_rows: list[dict] = []
            best_type = "outro"
            for s, t in classified:
                sv = await self._get(f"/votacoes/{s['id']}/votos")
                rows = sv.get("dados", []) or []
                # Prefer non-destaque on ties.
                better = (
                    len(rows) > best_n
                    or (len(rows) == best_n and best_type == "destaque" and t != "destaque")
                )
                if better:
                    best_n, best, best_rows, best_type = len(rows), s, rows, t
            chosen, chosen_rows = best, best_rows
            reason = f"fallback-most-votes-{best_type}" if best else "no-votes"

        meta = {
            "chosen_session_id": chosen["id"] if chosen else None,
            "chosen_descricao": (chosen or {}).get("descricao"),
            "reason": reason,
            "n_sessions": len(sessions),
            "n_principal": len(principals),
        }
        if not chosen:
            return [], meta

        votes: list[dict] = []
        for v in chosen_rows:
            votes.append({
                "legislator_camara_id": v.get("deputado_", {}).get("id"),
                "vote_value": self._normalize_vote(v.get("tipoVoto")),
                "party_orientation": self._normalize_orientation(v.get("orientacaoVoto")),
                "session_camara_id": chosen["id"],
                "voted_at": v.get("dataHoraVoto"),
            })
        return votes, meta

    # ── Normalization ───────────────────────────────────────────────────────

    def _normalize_legislator(self, raw: dict) -> dict:
        return {
            "camara_id": raw.get("id"),
            "name": raw.get("nome"),
            "display_name": raw.get("nomeCivil") or raw.get("nome"),
            "chamber": "camara",
            "state_uf": raw.get("siglaUf", ""),
            "party_acronym": raw.get("siglaPartido"),
            "photo_url": raw.get("urlFoto"),
        }

    def _normalize_legislator_detail(self, raw: dict) -> dict:
        # Detail endpoint nests current-status fields under ultimoStatus
        status = raw.get("ultimoStatus") or {}
        return {
            "camara_id": raw.get("id") or status.get("id"),
            "name": status.get("nome") or raw.get("nomeCivil", ""),
            "display_name": status.get("nomeEleitoral") or status.get("nome") or raw.get("nomeCivil"),
            "chamber": "camara",
            "state_uf": status.get("siglaUf", ""),
            "party_acronym": status.get("siglaPartido"),
            "photo_url": status.get("urlFoto"),
            "education_level": raw.get("escolaridade"),
            "declared_assets_brl": None,  # requires separate TSE dataset
            "cpf_hash": self._hash_cpf(raw.get("cpf", "")),
        }

    def _normalize_bill(self, raw: dict) -> dict:
        # urgency_regime: derived from statusProposicao.regime, which on the
        # detail endpoint contains strings like "Urgência", "Urgência (Art.
        # 155, RICD)", "Prioridade" or "Especial". List endpoint may omit
        # this field — falls back to False, will be filled in on the next
        # detail-fetch round.
        status_proposicao = raw.get("statusProposicao") or {}
        regime = (status_proposicao.get("regime") or "").lower()
        urgency_regime = any(
            w in regime for w in ("urgência", "urgencia", "prioridade")
        )
        return {
            "camara_id": raw.get("id"),
            "type": raw.get("siglaTipo"),
            "number": raw.get("numero"),
            "year": raw.get("ano"),
            "title": raw.get("ementa") or "",
            "summary_official": raw.get("ementa"),
            "status": status_proposicao.get("descricaoSituacao"),
            "presentation_date": raw.get("dataApresentacao"),
            "urgency_regime": urgency_regime,
        }

    def _normalize_vote(self, tipo_voto: str | None) -> str:
        return {
            "Sim": "sim",
            "Não": "não",
            "Abstenção": "abstencao",
            "Obstrução": "obstrucao",
            "Artigo 17": "ausente",
        }.get(tipo_voto or "", "ausente")

    def _normalize_orientation(self, orientation: str | None) -> str | None:
        return {
            "Sim": "sim",
            "Não": "não",
            "Livre": "livre",
            "Obstrução": "obstrucao",
        }.get(orientation or "")

    def _hash_cpf(self, cpf: str) -> str | None:
        clean = cpf.replace(".", "").replace("-", "").strip()
        return hashlib.sha256(clean.encode()).hexdigest() if clean else None
