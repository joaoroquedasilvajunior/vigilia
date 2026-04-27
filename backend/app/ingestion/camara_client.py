import asyncio
import hashlib
import time
from datetime import datetime, timedelta
from typing import AsyncGenerator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings

BASE_URL = settings.camara_api_base_url


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

        win_start = start_dt
        while win_start <= end_dt:
            win_end = min(win_start + timedelta(days=chunk_days - 1), end_dt)
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
            win_start = win_end + timedelta(days=1)

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
        return {
            "camara_id": raw.get("id"),
            "type": raw.get("siglaTipo"),
            "number": raw.get("numero"),
            "year": raw.get("ano"),
            "title": raw.get("ementa") or "",
            "summary_official": raw.get("ementa"),
            "status": (raw.get("statusProposicao") or {}).get("descricaoSituacao"),
            "presentation_date": raw.get("dataApresentacao"),
            "urgency_regime": False,
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
