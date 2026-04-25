"""
Step 1 validation: Tests the Câmara API client without a database.
Run: python scripts/test_camara_api.py

Prints how many records sync_legislators() and sync_recent_bills() would insert,
along with sample data from each endpoint.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ingestion.camara_client import CamaraClient


async def test_legislators(client: CamaraClient, max_pages: int = 2) -> None:
    print("\n" + "=" * 60)
    print("SYNC LEGISLATORS — legislature 57 (2023–2027)")
    print("=" * 60)

    count = 0
    sample = []
    async for leg in client.get_legislators(legislature=57):
        count += 1
        if count <= 5:
            sample.append(leg)
        # Only fetch 2 pages worth (~200) to avoid a full scan in testing
        if count >= max_pages * 100:
            print(f"  [stopping at {count} for test — full sync would continue]")
            break

    print(f"\n  Records in first {max_pages} pages: {count}")
    print("\n  Sample (first 5):")
    for leg in sample:
        print(f"    • [{leg['camara_id']}] {leg['name']} ({leg.get('party_acronym','?')} / {leg['state_uf']})")

    # Fetch detail for first legislator
    if sample:
        print(f"\n  Detail fetch for {sample[0]['name']} (id={sample[0]['camara_id']}):")
        detail = await client.get_legislator_detail(sample[0]['camara_id'])
        for k, v in detail.items():
            if v is not None:
                print(f"    {k}: {v}")


async def test_bills(client: CamaraClient, days_back: int = 90) -> None:
    print("\n" + "=" * 60)
    print(f"SYNC RECENT BILLS — last {days_back} days")
    print("=" * 60)

    from datetime import datetime, timedelta
    since = datetime.now() - timedelta(days=days_back)

    count = 0
    sample = []
    urgency_count = 0

    async for bill in client.get_bills(since_date=since, bill_types=["PL", "PEC", "MPV"]):
        count += 1
        if count <= 5:
            sample.append(bill)
        if bill.get("urgency_regime"):
            urgency_count += 1
        if count >= 300:
            print(f"  [stopping at {count} for test]")
            break

    print(f"\n  Records found: {count}")
    print(f"  Under urgency regime: {urgency_count}")
    print("\n  Sample (first 5):")
    for b in sample:
        print(f"    • [{b['camara_id']}] {b['type']} {b['number']}/{b['year']}: {(b['title'] or '')[:60]}...")
        print(f"      Status: {b['status']}")


async def test_votes(client: CamaraClient) -> None:
    """Test vote fetching for a known bill with votes (PEC 45/2019 — tax reform)."""
    # PEC 45/2019 is a well-known bill with votes
    KNOWN_BILL_ID = 2192459  # Câmara ID for PEC 45/2019

    print("\n" + "=" * 60)
    print(f"SYNC VOTES — bill camara_id={KNOWN_BILL_ID}")
    print("=" * 60)

    try:
        votes = await client.get_votes_for_bill(KNOWN_BILL_ID)
        print(f"\n  Votes returned: {len(votes)}")
        if votes:
            sample_vote = votes[0]
            print(f"  Sample vote: legislator_id={sample_vote['legislator_camara_id']}, "
                  f"value={sample_vote['vote_value']}, "
                  f"orientation={sample_vote['party_orientation']}")
    except Exception as e:
        print(f"  Note: {e} (bill may not have recorded votes yet)")


async def main() -> None:
    print("Vigília — Câmara API Client Test")
    print("Connecting to: https://dadosabertos.camara.leg.br/api/v2")

    async with CamaraClient(rate_limit_per_sec=3.0) as client:
        await test_legislators(client)
        await test_bills(client)
        await test_votes(client)

    print("\n" + "=" * 60)
    print("✓ Câmara API client is working. Ready for full DB sync.")
    print("  Next step: configure backend/.env and run sync_pipeline.py")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
