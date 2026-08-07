"""
CEOPRO AI - Market Perception Index scoring (spec S17).
Pure functions only - no DB access here, so the math is unit-testable without
a live database. Combines sentiment + source reliability + recency + volume +
entity relevance into a single 0-100 index, while preserving every
component's individual contribution (spec S17: "the system must preserve the
underlying contributions" so a dashboard can answer "why did the MPI change").
"""

import os
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

# Collection-method reliability weights. Not derived from the spec (which
# doesn't give exact numbers) - reflects spec S13's own stated preference
# ("prefer official APIs/RSS/structured data over scraping"), applied as a
# concrete weight rather than left as an unquantified principle.
RELIABILITY_WEIGHTS = {
    "PUBLIC_API": 1.0,
    "PUBLIC_FEED": 0.85,
    "MANUAL": 0.6,
}
DEFAULT_RELIABILITY_WEIGHT = 0.6

# Exponential recency decay - a review from today counts fully, one from
# RECENCY_HALF_LIFE_DAYS ago counts at half weight. Not spec-derived, a
# practical default (same "not derived from the spec" caveat as every other
# undomains-specified threshold in this codebase, e.g. forecasting's
# MIN_HISTORY_DAYS).
RECENCY_HALF_LIFE_DAYS = int(os.getenv("MPI_RECENCY_HALF_LIFE_DAYS", "90"))

# Volume confidence saturates at this many analyzed reviews - below it, the
# MPI is pulled toward the neutral midpoint (50) proportionally, so a
# handful of reviews can't swing the index as hard as a well-sampled one.
MIN_VOLUME_FOR_FULL_CONFIDENCE = int(os.getenv("MPI_MIN_VOLUME_FOR_FULL_CONFIDENCE", "20"))


@dataclass
class ReviewContribution:
    """
    One review's weighted contribution to the MPI - the atomic unit spec S17's
    "preserve the underlying contributions" requirement is about.
    """
    review_id: str
    sentiment_score: float  # positive_probability - negative_probability, in [-1, 1]
    recency_weight: float
    reliability_weight: float
    relevance_weight: float

    @property
    def combined_weight(self) -> float:
        return self.recency_weight * self.reliability_weight * self.relevance_weight


@dataclass
class MPIResult:
    mpi: float  # 0-100
    weighted_sentiment_score: float  # -1 to 1, before volume dampening
    volume_confidence: float  # 0-1
    review_count: int
    avg_recency_weight: float
    avg_reliability_weight: float
    label_counts: dict

    def as_dict(self) -> dict:
        return {
            "mpi": self.mpi,
            "weighted_sentiment_score": self.weighted_sentiment_score,
            "volume_confidence": self.volume_confidence,
            "review_count": self.review_count,
            "avg_recency_weight": self.avg_recency_weight,
            "avg_reliability_weight": self.avg_reliability_weight,
            "label_counts": self.label_counts,
        }


def recency_weight(review_date: date, as_of: date) -> float:
    age_days = max(0, (as_of - review_date).days)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def reliability_weight(collection_method: str) -> float:
    return RELIABILITY_WEIGHTS.get(collection_method, DEFAULT_RELIABILITY_WEIGHT)


def volume_confidence(review_count: int) -> float:
    return min(1.0, review_count / MIN_VOLUME_FOR_FULL_CONFIDENCE)


@dataclass
class MPIComparison:
    comparable: bool
    reason: str
    mpi_a: float
    mpi_b: float
    difference: Optional[float]  # None when not comparable - never a number computed from insufficient data

    def as_dict(self) -> dict:
        return {
            "comparable": self.comparable,
            "reason": self.reason,
            "mpi_a": self.mpi_a,
            "mpi_b": self.mpi_b,
            "difference": self.difference,
        }


def compare_mpi_results(result_a: MPIResult, result_b: MPIResult, min_volume_for_comparison: int) -> MPIComparison:
    """
    Spec S17: "must support cross-country analysis only when the comparison
    is statistically and economically meaningful" and "must not blindly
    compare raw sentiment volume between countries with radically different
    market sizes." Refuses to return a difference at all - not a
    low-confidence one, none - when either side is under the volume floor,
    rather than letting a well-sampled subject's real signal get diluted by
    a comparison against near-noise.
    """
    thin_sides = []
    if result_a.review_count < min_volume_for_comparison:
        thin_sides.append(f"side 'a' has only {result_a.review_count} review(s)")
    if result_b.review_count < min_volume_for_comparison:
        thin_sides.append(f"side 'b' has only {result_b.review_count} review(s)")

    if thin_sides:
        # Report every side that's actually thin, not just the first one
        # found - a caller debugging "why can't I compare these" needs to
        # know if *both* sides are under-sampled, not just one.
        return MPIComparison(
            comparable=False,
            reason=(
                f"{' and '.join(thin_sides)}, below the {min_volume_for_comparison}-review floor "
                f"for a meaningful comparison."
            ),
            mpi_a=result_a.mpi,
            mpi_b=result_b.mpi,
            difference=None,
        )

    return MPIComparison(
        comparable=True,
        reason="Both sides meet the minimum sample size for a meaningful comparison.",
        mpi_a=result_a.mpi,
        mpi_b=result_b.mpi,
        difference=round(result_a.mpi - result_b.mpi, 2),
    )


def compute_mpi(contributions: List[ReviewContribution], label_counts: dict) -> Optional[MPIResult]:
    """
    Returns None for zero contributions - an MPI computed from no data isn't
    a low-confidence result, it's not a result at all (mirrors sentiment's
    UNKNOWN-vs-LOW_SAMPLE_SIZE distinction).
    """
    if not contributions:
        return None

    total_weight = sum(c.combined_weight for c in contributions)
    if total_weight <= 0:
        weighted_sentiment_score = 0.0
    else:
        weighted_sentiment_score = sum(c.sentiment_score * c.combined_weight for c in contributions) / total_weight

    count = len(contributions)
    conf = volume_confidence(count)

    # Neutral midpoint (50) when confidence is zero, full swing toward 0/100
    # as confidence approaches 1 - sparse data pulls toward "uninformative"
    # rather than letting a handful of reviews swing the index freely.
    mpi = 50.0 + 50.0 * weighted_sentiment_score * conf

    return MPIResult(
        mpi=round(mpi, 2),
        weighted_sentiment_score=round(weighted_sentiment_score, 4),
        volume_confidence=round(conf, 4),
        review_count=count,
        avg_recency_weight=round(sum(c.recency_weight for c in contributions) / count, 4),
        avg_reliability_weight=round(sum(c.reliability_weight for c in contributions) / count, 4),
        label_counts=label_counts,
    )
