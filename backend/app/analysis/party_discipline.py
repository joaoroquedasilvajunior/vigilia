"""
Party discipline + absence-rate computation.

Two metrics, computed in pure SQL aggregates (no per-legislator iteration):

  1. Party discipline (per legislator):
       discipline = (votes where vote_value == party_orientation)
                   / (votes with explicit party_orientation, excluding 'livre')

     Required prerequisite: votes.party_orientation must be populated.
     See ingestion/orientation_pipeline.py — it backfills this column from
     Câmara's /votacoes/{id}/orientacoes endpoint.

  2. Absence rate (per legislator):
       absence_rate = (votes where vote_value = 'ausente') / (total votes)

     Caveat: the Câmara API only emits an 'ausente' row when the legislator
     was explicitly marked Article-17-absent during a recorded vote. True
     "didn't show up to the session at all" absences don't appear as rows
     and aren't captured here. The metric is therefore a *lower bound* on
     real absence — useful for relative comparison between deputies, but
     not for absolute absentee accounting.

  3. Party cohesion = mean(discipline_score) across each party's members.

Entry point: compute_discipline_and_absence()
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


_DISCIPLINE_SQL = text("""
    WITH disciplined AS (
        SELECT
            legislator_id,
            COUNT(*) FILTER (
                WHERE vote_value = party_orientation
            )::float
            / NULLIF(COUNT(*), 0) AS score,
            COUNT(*)              AS total_votes
        FROM votes
        WHERE party_orientation IS NOT NULL
          AND party_orientation NOT IN ('livre', 'obstrucao')
          AND vote_value         NOT IN ('ausente')
        GROUP BY legislator_id
    )
    UPDATE legislators l
    SET party_discipline_score = d.score
    FROM disciplined d
    WHERE l.id = d.legislator_id
""")

_ABSENCE_SQL = text("""
    WITH absences AS (
        SELECT
            legislator_id,
            SUM(CASE WHEN vote_value = 'ausente' THEN 1 ELSE 0 END)::float
              / NULLIF(COUNT(*), 0) AS rate
        FROM votes
        GROUP BY legislator_id
    )
    UPDATE legislators l
    SET absence_rate = a.rate
    FROM absences a
    WHERE l.id = a.legislator_id
""")

_PARTY_COHESION_SQL = text("""
    WITH party_avg AS (
        SELECT
            nominal_party_id AS party_id,
            AVG(party_discipline_score) AS cohesion
        FROM legislators
        WHERE party_discipline_score IS NOT NULL
          AND nominal_party_id IS NOT NULL
        GROUP BY nominal_party_id
    )
    UPDATE parties p
    SET cohesion_score = a.cohesion
    FROM party_avg a
    WHERE p.id = a.party_id
""")


async def compute_discipline_and_absence() -> None:
    """
    Run all three updates in one transaction:
      - legislators.party_discipline_score
      - legislators.absence_rate
      - parties.cohesion_score (depends on legislator scores being set first)

    Idempotent: rerunning recomputes from current vote data.
    """
    logger.info("compute_discipline_and_absence: starting")
    async with AsyncSessionLocal() as db:
        disc_res    = await db.execute(_DISCIPLINE_SQL)
        absent_res  = await db.execute(_ABSENCE_SQL)
        cohesion_res = await db.execute(_PARTY_COHESION_SQL)
        await db.commit()

    logger.info(
        "compute_discipline_and_absence: DONE — "
        "discipline_updated=%d absence_updated=%d party_cohesion_updated=%d",
        disc_res.rowcount, absent_res.rowcount, cohesion_res.rowcount,
    )


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(compute_discipline_and_absence())
