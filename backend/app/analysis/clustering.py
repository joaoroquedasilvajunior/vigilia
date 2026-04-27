"""
Behavioral clustering of legislators by actual voting patterns.

Why this exists: Brazilian deputies often vote against their own party
(the "Centrão" phenomenon). Grouping by *behavior* rather than party
label reveals the real coalitions — Bancada Ruralista cuts across PL,
PP, União Brasil; Bancada Evangélica spans dozens of small parties; etc.

Algorithm:
  1. Build a sparse legislator × bill matrix (1=sim, -1=não, 0=other)
  2. Filter: bills with enough votes, legislators with enough vote rows
  3. KMeans over k ∈ candidate range, pick best by silhouette score
  4. Auto-label clusters via Haiku from voting + party + theme signal
  5. Persist behavioral_clusters + update legislators.behavioral_cluster_id

Adaptive thresholds: when vote coverage is sparse, the per-bill and
per-legislator thresholds drop so the pipeline still produces *some*
clustering. Quality improves automatically as vote data grows.

Entry point: compute_clusters()
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from datetime import datetime

import anthropic
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import AsyncSessionLocal
from app.models import (
    BehavioralCluster,
    Bill,
    Donor,
    DonorLink,
    Legislator,
    Party,
    Vote,
)

logger = logging.getLogger(__name__)

# ── Vote → numeric signal ─────────────────────────────────────────────────────
VOTE_SCORE = {
    "sim": 1.0,
    "não": -1.0,
    "nao": -1.0,
    "abstenção": 0.0,
    "abstencao": 0.0,
    "ausente": 0.0,
}

# Thresholds — see _adaptive_thresholds for the runtime relaxation logic
TARGET_MIN_VOTES_PER_BILL       = 50
TARGET_MIN_BILLS_PER_LEGISLATOR = 3
CANDIDATE_K_VALUES              = [3, 4, 5, 6, 7, 8, 9, 10]


# ────────────────────────────────────────────────────────────────────────────
# 1. Load voting matrix
# ────────────────────────────────────────────────────────────────────────────
async def _load_voting_matrix() -> pd.DataFrame:
    """
    Returns a DataFrame indexed by legislator_id, columns by bill_id.
    Cell values are float in {-1, 0, 1, NaN}; NaN means "didn't vote on this bill".
    """
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Vote.legislator_id, Vote.bill_id, Vote.vote_value)
            )
        ).all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(
        [(str(r.legislator_id), str(r.bill_id), VOTE_SCORE.get((r.vote_value or "").lower(), 0.0))
         for r in rows],
        columns=["legislator_id", "bill_id", "score"],
    )
    matrix = df.pivot_table(
        index="legislator_id", columns="bill_id", values="score", aggfunc="last"
    )
    return matrix


def _adaptive_thresholds(matrix: pd.DataFrame) -> tuple[int, int]:
    """
    Pick (min_votes_per_bill, min_bills_per_legislator) such that
    we keep some signal even when vote coverage is sparse.
    """
    n_bills = matrix.shape[1]
    n_legislators = matrix.shape[0]

    # Start at target; relax until we have at least 4 bills × 30 legislators
    bill_thr = TARGET_MIN_VOTES_PER_BILL
    while bill_thr > 5:
        kept = (matrix.notna().sum(axis=0) >= bill_thr).sum()
        if kept >= 4:
            break
        bill_thr -= 5

    leg_thr = TARGET_MIN_BILLS_PER_LEGISLATOR
    # If we have fewer total bills than the target, drop legislator threshold to half
    if n_bills < TARGET_MIN_BILLS_PER_LEGISLATOR * 2:
        leg_thr = max(1, n_bills // 2)

    return bill_thr, leg_thr


def _filter_matrix(matrix: pd.DataFrame, min_votes_per_bill: int,
                   min_bills_per_legislator: int) -> pd.DataFrame:
    """Drop sparse bills and sparse legislators."""
    if matrix.empty:
        return matrix
    # Bills: at least N legislators voted
    keep_bills = matrix.columns[matrix.notna().sum(axis=0) >= min_votes_per_bill]
    matrix = matrix[keep_bills]
    if matrix.empty:
        return matrix
    # Legislators: voted on at least M bills
    keep_legs = matrix.index[matrix.notna().sum(axis=1) >= min_bills_per_legislator]
    return matrix.loc[keep_legs]


# ────────────────────────────────────────────────────────────────────────────
# 2. K-means with silhouette-driven k selection
# ────────────────────────────────────────────────────────────────────────────
def _run_kmeans_with_k_search(X: np.ndarray, candidate_k: list[int]
                              ) -> tuple[KMeans, int, float]:
    """
    Run KMeans for each candidate k, return best by silhouette score.
    Falls back to smallest valid k if matrix doesn't support large k.
    """
    n_samples = X.shape[0]
    valid_k = [k for k in candidate_k if 2 <= k < n_samples]
    if not valid_k:
        # Degenerate case: too few samples to split — return single-cluster KMeans
        km = KMeans(n_clusters=1, random_state=42, n_init=10).fit(X)
        return km, 1, 0.0

    best_km = None
    best_k = None
    best_score = -1.0
    for k in valid_k:
        km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        # silhouette needs at least 2 distinct cluster labels
        if len(set(km.labels_)) < 2:
            continue
        try:
            score = silhouette_score(X, km.labels_)
        except ValueError:
            continue
        logger.info("kmeans k=%d silhouette=%.4f", k, score)
        if score > best_score:
            best_km, best_k, best_score = km, k, score

    if best_km is None:
        # All k values failed silhouette — fall back to smallest valid
        k = valid_k[0]
        best_km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X)
        best_k = k
        best_score = 0.0

    return best_km, best_k, best_score


# ────────────────────────────────────────────────────────────────────────────
# 3. Cluster characterization (parties, themes, donor types)
# ────────────────────────────────────────────────────────────────────────────
async def _cluster_signal(legislator_ids: list[str]) -> dict:
    """
    Pull the signal we need to label a cluster: party distribution,
    dominant bill themes (from theme_tags weighted by 'sim' votes),
    and donor source mix.
    """
    async with AsyncSessionLocal() as db:
        # Party distribution
        party_rows = (
            await db.execute(
                select(Party.acronym, Legislator.id)
                .outerjoin(Party, Legislator.nominal_party_id == Party.id)
                .where(Legislator.id.in_(legislator_ids))
            )
        ).all()
        party_counter = Counter(r.acronym or "(sem partido)" for r in party_rows)

        # Theme distribution: themes of bills they voted SIM on
        theme_rows = (
            await db.execute(
                select(Bill.theme_tags, Vote.vote_value)
                .join(Vote, Vote.bill_id == Bill.id)
                .where(Vote.legislator_id.in_(legislator_ids))
                .where(Bill.theme_tags.is_not(None))
            )
        ).all()
        theme_counter: Counter = Counter()
        for r in theme_rows:
            if r.vote_value == "sim" and r.theme_tags:
                theme_counter.update(r.theme_tags)

        # Donor source mix
        donor_rows = (
            await db.execute(
                select(Donor.entity_type, Donor.name, DonorLink.amount_brl)
                .join(DonorLink, Donor.id == DonorLink.donor_id)
                .where(DonorLink.legislator_id.in_(legislator_ids))
            )
        ).all()
        donor_total = sum(float(r.amount_brl or 0) for r in donor_rows) or 1.0
        party_fund_amt = sum(
            float(r.amount_brl or 0) for r in donor_rows
            if r.name and ("direção" in r.name.lower() or "direcao" in r.name.lower())
        )
        individual_amt = sum(
            float(r.amount_brl or 0) for r in donor_rows
            if r.entity_type == "pessoa_fisica"
            and not (r.name and ("direção" in r.name.lower() or "direcao" in r.name.lower()))
        )
        company_amt = sum(
            float(r.amount_brl or 0) for r in donor_rows
            if r.entity_type == "pessoa_juridica"
        )

    return {
        "parties":     party_counter.most_common(8),
        "themes":      theme_counter.most_common(6),
        "funding_pct": {
            "party_fund": round(100 * party_fund_amt / donor_total, 1),
            "individual": round(100 * individual_amt / donor_total, 1),
            "company":    round(100 * company_amt / donor_total, 1),
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# 4. Cluster auto-labeling via Haiku
# ────────────────────────────────────────────────────────────────────────────
_LABEL_SYSTEM = """\
Você nomeia coalizões legislativas brasileiras. Receberá padrões de voto, \
partidos predominantes, temas e fontes de financiamento de um cluster de \
deputados federais. Responda APENAS com um rótulo curto (máximo 3 palavras), \
sem texto adicional, sem aspas, sem pontuação final.

Exemplos válidos: Bancada Ruralista, Bloco Progressista, Centrão Financeiro,
Bancada Evangélica, Oposição Liberal, Bloco Governista."""

_LABEL_TEMPLATE = """\
Cluster com {n} deputados.
Partidos predominantes: {parties}
Temas votados favoravelmente: {themes}
Fontes de financiamento: {funding_pct}

Sugira um rótulo curto (até 3 palavras) que descreva esta coalizão."""


async def _label_cluster(client: anthropic.AsyncAnthropic, signal: dict, n: int) -> str:
    """One Haiku call → cluster label."""
    parties_str = ", ".join(f"{p}({c})" for p, c in signal["parties"][:5]) or "—"
    themes_str  = ", ".join(f"{t}({c})" for t, c in signal["themes"][:4]) or "—"
    funding_str = (
        f"FEFC {signal['funding_pct']['party_fund']}%, "
        f"PF {signal['funding_pct']['individual']}%, "
        f"PJ {signal['funding_pct']['company']}%"
    )
    prompt = _LABEL_TEMPLATE.format(
        n=n, parties=parties_str, themes=themes_str, funding_pct=funding_str,
    )
    try:
        resp = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=32,
            system=_LABEL_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        # Strip stray quotes / punctuation / fences
        raw = re.sub(r"^[\"'`]+|[\"'`.;]+$", "", raw)
        raw = re.sub(r"^```.*?```$", "", raw, flags=re.DOTALL).strip()
        return raw[:80] or f"Cluster {n} membros"
    except Exception as exc:
        logger.warning("_label_cluster failed: %s", exc)
        return f"Cluster {n} membros"


# ────────────────────────────────────────────────────────────────────────────
# 5. Cohesion score
# ────────────────────────────────────────────────────────────────────────────
def _cohesion_score(member_matrix: pd.DataFrame) -> float:
    """
    Average pairwise vote agreement within a cluster.
    1.0 = unanimous on every bill where members voted.
    0.0 = randomly split.
    Computed bill-by-bill, then averaged.
    """
    if member_matrix.shape[0] < 2 or member_matrix.shape[1] < 1:
        return 0.0
    bill_scores = []
    for col in member_matrix.columns:
        votes = member_matrix[col].dropna()
        if len(votes) < 2:
            continue
        # Convert to {sim, não, abstain} categorical, take max share
        counts = votes.value_counts()
        bill_scores.append(counts.max() / counts.sum())
    return float(np.mean(bill_scores)) if bill_scores else 0.0


# ────────────────────────────────────────────────────────────────────────────
# 6. Main pipeline
# ────────────────────────────────────────────────────────────────────────────
async def compute_clusters() -> None:
    """
    Full pipeline: matrix → kmeans → label → persist.
    Idempotent: replaces previous behavioral_clusters and rewires legislator FKs.
    """
    logger.info("compute_clusters: starting")
    matrix = await _load_voting_matrix()
    if matrix.empty:
        logger.warning("compute_clusters: no votes in DB; aborting")
        return

    bill_thr, leg_thr = _adaptive_thresholds(matrix)
    logger.info(
        "compute_clusters: thresholds — min_votes/bill=%d min_bills/leg=%d "
        "(starting matrix: %d legs × %d bills)",
        bill_thr, leg_thr, matrix.shape[0], matrix.shape[1],
    )
    filtered = _filter_matrix(matrix, bill_thr, leg_thr)
    if filtered.shape[0] < 5 or filtered.shape[1] < 1:
        logger.warning(
            "compute_clusters: insufficient signal after filter "
            "(%d legs × %d bills); aborting cleanly",
            filtered.shape[0], filtered.shape[1],
        )
        return

    logger.info(
        "compute_clusters: filtered matrix %d legs × %d bills",
        filtered.shape[0], filtered.shape[1],
    )

    # Impute missing → 0 (didn't vote ≈ neutral signal)
    imputer = SimpleImputer(strategy="constant", fill_value=0.0)
    X_imp = imputer.fit_transform(filtered.values)
    # Standardize so each bill is mean-0 std-1
    scaler = StandardScaler()
    X = scaler.fit_transform(X_imp)

    km, k, silhouette = _run_kmeans_with_k_search(X, CANDIDATE_K_VALUES)
    logger.info("compute_clusters: chosen k=%d silhouette=%.4f", k, silhouette)

    # Build cluster → [legislator_id] mapping
    legislator_ids = list(filtered.index)
    clusters: dict[int, list[str]] = {}
    for leg_id, label in zip(legislator_ids, km.labels_):
        clusters.setdefault(int(label), []).append(leg_id)

    # Characterise + label each cluster
    client = anthropic.AsyncAnthropic()
    cluster_records: list[dict] = []  # rows for behavioral_clusters
    leg_to_cluster_pk: dict[str, str] = {}  # legislator_id → cluster pk uuid

    for cluster_idx, member_ids in clusters.items():
        signal = await _cluster_signal(member_ids)
        label = await _label_cluster(client, signal, len(member_ids))
        cohesion = _cohesion_score(filtered.loc[member_ids])
        record = {
            "label":            label,
            "description":      f"Auto-gerado por k-means k={k} (silhouette {silhouette:.3f})",
            "dominant_themes":  [t for t, _ in signal["themes"]][:5] or None,
            "member_count":     len(member_ids),
            "cohesion_score":   round(cohesion, 4),
            "algorithm":        "kmeans",
            "algorithm_params": {
                "k":                  k,
                "silhouette":         round(silhouette, 4),
                "min_votes_per_bill": bill_thr,
                "min_bills_per_leg":  leg_thr,
                "n_bills":            filtered.shape[1],
                "n_legislators":      filtered.shape[0],
                "parties_top":        signal["parties"][:5],
                "funding_pct":        signal["funding_pct"],
            },
            "computed_at":      datetime.now(),
            "_member_ids":      member_ids,
        }
        cluster_records.append(record)

    # Persist: wipe-and-replace approach is simplest given idempotency need
    async with AsyncSessionLocal() as db:
        # 1. Detach all legislators from any current cluster (to avoid FK errors on delete)
        await db.execute(
            update(Legislator)
            .values(behavioral_cluster_id=None)
        )
        await db.flush()
        # 2. Wipe old cluster rows
        await db.execute(BehavioralCluster.__table__.delete())
        await db.flush()

        # 3. Insert new clusters and capture their generated UUIDs
        for rec in cluster_records:
            ins = pg_insert(BehavioralCluster).values(
                {k: v for k, v in rec.items() if not k.startswith("_")}
            ).returning(BehavioralCluster.id)
            new_id = (await db.execute(ins)).scalar_one()
            for leg_id in rec["_member_ids"]:
                leg_to_cluster_pk[leg_id] = str(new_id)

        # 4. Wire each legislator to its cluster
        for leg_id, cluster_pk in leg_to_cluster_pk.items():
            await db.execute(
                update(Legislator)
                .where(Legislator.id == leg_id)
                .values(behavioral_cluster_id=cluster_pk)
            )

        await db.commit()

    logger.info(
        "compute_clusters: DONE — %d clusters, %d legislators wired, "
        "labels=%s",
        len(cluster_records),
        len(leg_to_cluster_pk),
        [r["label"] for r in cluster_records],
    )


if __name__ == "__main__":
    async def _main() -> None:
        logging.basicConfig(level=logging.INFO)
        await compute_clusters()
    asyncio.run(_main())
