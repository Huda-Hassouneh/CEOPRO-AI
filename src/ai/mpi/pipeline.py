"""
CEOPRO AI - Market Perception Index Pipeline (spec S17, S22, S23).
Orchestrates: load already-analyzed reviews for a subject -> weight each by
recency/source-reliability/entity-relevance -> combine into a single 0-100
index, volume-dampened toward the neutral midpoint when under-sampled ->
persist an evidence_records FACT preserving every component's contribution
(spec S17's "why did the MPI change" requirement), never just the final
number. Only writes to evidence_records - reviews/sentiment_results are
owned by other pipelines.
"""

import logging
from datetime import date
from typing import Optional

from src.ai.mpi import cold_start, data_access, evidence
from src.ai.mpi.scoring import (
    MPIComparison,
    ReviewContribution,
    compare_mpi_results,
    compute_mpi,
    recency_weight,
    reliability_weight,
)

logger = logging.getLogger("CEOPRO_AI_MPI_PIPELINE")

SOURCE_MODULE = "ai.mpi"

# Entity relevance defaults to 1.0: every review reaching this pipeline is
# already explicitly linked to its subject via reviews.subject_type/
# product_id/competitor_id (spec S10's data model), not free-text matched -
# so relevance today is "linked or not considered at all," not a continuous
# score. A real NLP relevance signal (e.g. from src/ai/extraction/'s NER
# matching) is a natural future refinement once that's wired to write
# somewhere queryable (PENDING_ACTIONS.md #4).
DEFAULT_ENTITY_RELEVANCE = 1.0


def _build_contributions(reviews: list, as_of: date) -> list:
    contributions = []
    for review in reviews:
        if review["effective_date"] is None:
            continue
        sentiment_score = review["positive_probability"] - review["negative_probability"]
        contributions.append(
            ReviewContribution(
                review_id=review["review_id"],
                sentiment_score=sentiment_score,
                recency_weight=recency_weight(review["effective_date"], as_of),
                reliability_weight=reliability_weight(review["collection_method"]),
                relevance_weight=DEFAULT_ENTITY_RELEVANCE,
            )
        )
    return contributions


def _label_counts(reviews: list) -> dict:
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for review in reviews:
        counts[review["label"]] = counts.get(review["label"], 0) + 1
    return counts


def get_subject_mpi(
    conn, tenant_id: str, subject_type: str, subject_id: Optional[str] = None, as_of: Optional[date] = None
) -> dict:
    as_of = as_of or date.today()
    reviews = data_access.load_scored_reviews(conn, tenant_id, subject_type, subject_id)
    country_context = data_access.load_country_context(conn, tenant_id, subject_type, subject_id)

    contributions = _build_contributions(reviews, as_of)
    label_counts = _label_counts(reviews)
    result = compute_mpi(contributions, label_counts)

    if result is None:
        # Either no reviews at all, or every review had no effective_date
        # (both review_date and collected_at NULL) and got filtered out -
        # same UNKNOWN outcome either way: nothing usable to score.
        explanation = f"No analyzed reviews are available yet for this {subject_type.lower()}."
        evidence_id = evidence.insert_evidence_record(
            conn,
            tenant_id,
            "UNKNOWN",
            SOURCE_MODULE,
            {"subject_type": subject_type, "subject_id": subject_id},
            None,
            explanation,
            None,
            country_context,
        )
        conn.commit()
        logger.info(f"No usable reviews for MPI tenant={tenant_id} subject={subject_type}/{subject_id}")
        return {"status": "UNKNOWN", "evidence_id": evidence_id}

    sample_assessment = cold_start.assess(result.review_count)

    if sample_assessment.sufficient:
        confidence_score = round(0.4 + 0.55 * result.volume_confidence, 2)
        explanation = (
            f"MPI={result.mpi} from {result.review_count} analyzed reviews "
            f"(weighted sentiment={result.weighted_sentiment_score}, volume confidence={result.volume_confidence}, "
            f"avg recency weight={result.avg_recency_weight}, avg source-reliability weight={result.avg_reliability_weight}: "
            f"{label_counts['positive']} positive, {label_counts['neutral']} neutral, {label_counts['negative']} negative)."
        )
    else:
        confidence_score = 0.2
        explanation = (
            f"LOW SAMPLE SIZE: MPI={result.mpi} is based on only {result.review_count} analyzed review(s) "
            f"(minimum {sample_assessment.minimum_required} required) - this index should not be treated as a "
            f"reliable market conclusion."
        )

    evidence_id = evidence.insert_evidence_record(
        conn,
        tenant_id,
        "FACT",
        SOURCE_MODULE,
        {"subject_type": subject_type, "subject_id": subject_id, **result.as_dict()},
        confidence_score,
        explanation,
        None,
        country_context,
    )
    conn.commit()

    logger.info(
        f"MPI written tenant={tenant_id} subject={subject_type}/{subject_id} "
        f"mpi={result.mpi} status={sample_assessment.status} evidence_id={evidence_id}"
    )

    return {
        "status": "OK",
        "evidence_id": evidence_id,
        "mpi": result.mpi,
        "sample_size": sample_assessment.as_dict(),
        **result.as_dict(),
    }


def compare_subjects(
    conn,
    tenant_id: str,
    subject_a: tuple,
    subject_b: tuple,
    as_of: Optional[date] = None,
    min_volume_for_comparison: int = 10,
) -> MPIComparison:
    """
    subject_a/subject_b are (subject_type, subject_id) tuples. Computes each
    side's MPI in-memory (does not write evidence for either side - callers
    that also want the individual MPIs persisted should call
    get_subject_mpi() separately) and applies spec S17's meaningful-
    comparison guard before returning a difference.
    """
    as_of = as_of or date.today()

    def _score(subject_type: str, subject_id: Optional[str]):
        reviews = data_access.load_scored_reviews(conn, tenant_id, subject_type, subject_id)
        contributions = _build_contributions(reviews, as_of)
        return compute_mpi(contributions, _label_counts(reviews))

    result_a = _score(*subject_a)
    result_b = _score(*subject_b)

    if result_a is None or result_b is None:
        empty_side = "a" if result_a is None else "b"
        return MPIComparison(
            comparable=False,
            reason=f"Side '{empty_side}' has no analyzed reviews at all.",
            mpi_a=result_a.mpi if result_a else 0.0,
            mpi_b=result_b.mpi if result_b else 0.0,
            difference=None,
        )

    return compare_mpi_results(result_a, result_b, min_volume_for_comparison)
