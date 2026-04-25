"""
Step 2 validation: Tests all 5 Farol queries against the running API.
Run after the backend is up: python scripts/test_farol_queries.py [base_url]

Default base_url: http://localhost:8000/api/v1
"""
import asyncio
import json
import sys

import httpx

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/api/v1"

QUERIES = [
    "Como votou o deputado Nikolas Ferreira nos últimos projetos?",
    "Quais projetos de lei sobre trabalho estão em tramitação?",
    "Quais deputados receberam doações do agronegócio?",
    "Existe algum projeto com risco constitucional alto votado recentemente?",
    "O que é o regime de urgência e quais projetos estão sob ele agora?",
]


async def run_query(client: httpx.AsyncClient, message: str, session_id: str | None) -> dict:
    resp = await client.post(
        f"{BASE_URL}/farol/chat",
        json={"message": message, "session_id": session_id},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()


async def main() -> None:
    print(f"Farol E2E Test — {BASE_URL}\n")
    print("=" * 70)

    session_id = None

    async with httpx.AsyncClient() as client:
        for i, query in enumerate(QUERIES, 1):
            print(f"\nQuery {i}: {query}")
            print("-" * 50)
            try:
                result = await run_query(client, query, session_id)
                session_id = result["session_id"]

                print(f"Session ID : {session_id}")
                print(f"Sources    : {json.dumps(result['sources'], ensure_ascii=False, indent=2)}")
                print(f"\nFarol says:\n{result['response']}")
            except httpx.HTTPError as e:
                print(f"HTTP error: {e}")
            except Exception as e:
                print(f"Error: {e}")
            print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
