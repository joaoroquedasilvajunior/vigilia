"""
Fetch legislators and recent bills from Câmara API and write to JSON files.
Used by Claude MCP sync workflow — output files are then inserted via execute_sql.
"""
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timedelta

import httpx

BASE = "https://dadosabertos.camara.leg.br/api/v2"
LEGISLATURE = 57


async def get_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> dict:
    for attempt in range(5):
        try:
            resp = await client.get(url, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            if attempt == 4:
                raise
            wait = 2 ** attempt
            print(f"  retry {attempt+1} after {wait}s: {e}", flush=True)
            await asyncio.sleep(wait)


async def fetch_legislators(client: httpx.AsyncClient) -> list[dict]:
    rows = []
    page = 1
    print("Fetching legislators list...", flush=True)
    while True:
        data = await get_json(
            client, f"{BASE}/deputados",
            {"idLegislatura": LEGISLATURE, "itens": 100, "pagina": page}
        )
        items = data.get("dados", [])
        if not items:
            break
        for item in items:
            camara_id = item.get("id")
            if not camara_id:
                continue
            try:
                detail_data = await get_json(client, f"{BASE}/deputados/{camara_id}")
                raw = detail_data.get("dados", {})
                status = raw.get("ultimoStatus") or {}
                cpf = raw.get("cpf", "")
                cpf_hash = hashlib.sha256(cpf.encode()).hexdigest() if cpf else None
                rows.append({
                    "camara_id": camara_id,
                    "name": status.get("nome") or raw.get("nomeCivil", ""),
                    "display_name": status.get("nomeEleitoral") or status.get("nome") or raw.get("nomeCivil"),
                    "chamber": "camara",
                    "state_uf": status.get("siglaUf") or item.get("siglaUf", ""),
                    "party_acronym": status.get("siglaPartido") or item.get("siglaPartido"),
                    "photo_url": status.get("urlFoto") or item.get("urlFoto"),
                    "education_level": raw.get("escolaridade"),
                    "cpf_hash": cpf_hash,
                })
            except Exception as e:
                print(f"  skip legislator {camara_id}: {e}", flush=True)
        print(f"  page {page}: {len(items)} deputies, total so far: {len(rows)}", flush=True)
        # check for next page
        links = data.get("links", [])
        if not any(l.get("rel") == "next" for l in links):
            break
        page += 1
    return rows


async def fetch_bills(client: httpx.AsyncClient, days_back: int = 90) -> list[dict]:
    since = datetime.now() - timedelta(days=days_back)
    rows = []
    page = 1
    print(f"Fetching bills since {since.date()}...", flush=True)
    while True:
        data = await get_json(
            client, f"{BASE}/proposicoes",
            {
                "dataInicio": since.strftime("%Y-%m-%d"),
                "itens": 100,
                "pagina": page,
                "ordem": "ASC",
                "ordenarPor": "id",
            }
        )
        items = data.get("dados", [])
        if not items:
            break
        for item in items:
            camara_id = item.get("id")
            if not camara_id:
                continue
            number_str = item.get("numero", "")
            try:
                number = int(number_str) if number_str else None
            except ValueError:
                number = None
            year_str = item.get("ano", "")
            try:
                year = int(year_str) if year_str else None
            except ValueError:
                year = None
            if not number or not year:
                continue
            rows.append({
                "camara_id": camara_id,
                "type": item.get("siglaTipo"),
                "number": number,
                "year": year,
                "title": item.get("ementa") or "",
                "summary_official": item.get("ementa"),
                "status": None,
                "urgency_regime": False,
                "presentation_date": None,
            })
        print(f"  page {page}: {len(items)} bills, total so far: {len(rows)}", flush=True)
        links = data.get("links", [])
        if not any(l.get("rel") == "next" for l in links):
            break
        page += 1
    return rows


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    async with httpx.AsyncClient(
        headers={"Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        if mode in ("legislators", "both"):
            legs = await fetch_legislators(client)
            with open("/tmp/vigilia_legislators.json", "w") as f:
                json.dump(legs, f)
            print(f"Wrote {len(legs)} legislators to /tmp/vigilia_legislators.json")

        if mode in ("bills", "both"):
            bills = await fetch_bills(client)
            with open("/tmp/vigilia_bills.json", "w") as f:
                json.dump(bills, f)
            print(f"Wrote {len(bills)} bills to /tmp/vigilia_bills.json")


if __name__ == "__main__":
    asyncio.run(main())
