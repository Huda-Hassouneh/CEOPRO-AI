"""
KEEL - Sentiment Analysis Pipeline (spec S16, S22, S23).
Two entry points:
  - classify_and_store_reviews: runs the classifier over unanalyzed reviews
    and writes sentiment_results rows. Bulk/background labeling, not itself
    a user-facing conclusion, so it writes no evidence_records (mirrors how
    src/ai/rag/embeddings.py's embedding step is infrastructure, not an
    evidence-bearing output).
  - get_subject_sentiment_summary: aggregates already-analyzed sentiment for
    one subject (a product, a competitor, or the business overall), applies
    the LOW SAMPLE SIZE policy (spec S16), and is the only function here
    that writes to evidence_records - this is the user-facing conclusion.
"""

import logging
from typing import Optional

from src.ai.sentiment import cold_start, data_access, evidence, model

logger = logging.getLogger("CEOPRO_AI_SENTIMENT_PIPELINE")

SOURCE_MODULE = "ai.sentiment"

# Aggregate FACT evidence isn't a per-observation model score, so this
# reflects sample-size trust in the aggregate rather than any single
# prediction's probability - deliberately coarse, same style as
# src/ai/forecasting/pipeline.py's baseline-path confidence assignment.
CONFIDENCE_SUFFICIENT_SAMPLE = 0.8
CONFIDENCE_LOW_SAMPLE = 0.3

_SAVEPOINT_NAME = "sentiment_pipeline_write"


def classify_and_store_reviews(conn, tenant_id: str, batch_size: int = 100) -> dict:
    """
    Each review's insert_sentiment_result() call is isolated in its own
    SAVEPOINT (mirrors src/ai/extraction/ingestion_pipeline.py's
    _execute_in_savepoint - the same fix for the same class of problem).
    Without this, one review that fails at the database level (a
    constraint violation, an encoding edge case) leaves the whole
    transaction aborted, so nothing in this batch commits - and because
    load_unanalyzed_reviews() selects deterministically oldest-first, that
    same review is first in line again on the very next run, permanently
    blocking every review behind it. A per-review SAVEPOINT means one bad
    review is skipped (still unanalyzed, still eligible for a future
    retry/fix) without blocking the other reviews in this same batch from
    being classified and committed now.
    """
    # Plan allowance (records per billing period): analyse at most what is
    # left; the rest stay unanalysed and are picked up after an upgrade or
    # in the next period.
    from src.ai.core import usage

    left = usage.remaining(conn, tenant_id, usage.SENTIMENT_ANALYSIS)
    if left == 0:
        return {"status": "PLAN_LIMIT", "analyzed_count": 0}
    if left is not None:
        batch_size = min(batch_size, left)
    # Star-rating stand-ins (written while the model was unavailable) come
    # after never-analyzed reviews and are replaced once the model answers.
    reviews = data_access.load_unanalyzed_reviews(conn, tenant_id, limit=batch_size, include_rating_fallbacks=True)
    if not reviews:
        return {"status": "OK", "analyzed_count": 0}

    # ``remaining()`` above is only a useful batch-size hint. It is not a
    # reservation: another request or worker can consume that allowance before
    # this classifier finishes. Reserve the selected records atomically in the
    # same transaction as their sentiment rows, then settle to the number that
    # was actually persisted. This keeps the existing per-record unit and
    # releases failed/duplicate writes without charging twice.
    new_count = sum(not r.get("upgrade") for r in reviews)
    reservation = None
    try:
        if new_count:
            reservation = usage.reserve(conn, tenant_id, usage.SENTIMENT_ANALYSIS, new_count)
    except usage.PlanLimitReached as exc:
        if exc.reason == "QUOTA_EXHAUSTED":
            return {"status": "PLAN_LIMIT", "analyzed_count": 0}
        raise

    try:
        predictions = model.classify_or_unavailable([r["review_text"] for r in reviews])
        method = "model"
    except model.SentimentModelUnavailable as exc:
        # The text model is unreachable: use the customer's own star rating
        # where there is one; reviews without a rating stay unanalyzed.
        logger.warning("sentiment model unavailable (%s); using star ratings where present", exc)
        if not new_count:
            return {"status": "MODEL_UNAVAILABLE", "analyzed_count": 0, "method": "star_rating"}
        reviews = data_access.load_unanalyzed_reviews(conn, tenant_id, limit=new_count, rated_only=True)
        predictions = [model.predict_from_rating(r.get("review_rating")) for r in reviews]
        method = "star_rating"
        pairs = [(r, p) for r, p in zip(reviews, predictions) if p is not None]
        if not pairs:
            if reservation is not None:
                usage.settle(conn, reservation, 0)
            conn.commit()
            return {"status": "MODEL_UNAVAILABLE", "analyzed_count": 0, "method": method}
        reviews, predictions = [r for r, _ in pairs], [p for _, p in pairs]

    analyzed_count = 0
    upgraded_count = 0
    failed_count = 0
    for review, prediction in zip(reviews, predictions):
        with conn.cursor() as cursor:
            cursor.execute(f"SAVEPOINT {_SAVEPOINT_NAME};")
        try:
            evidence.insert_sentiment_result(
                conn,
                review["review_id"],
                tenant_id,
                prediction.label,
                prediction.positive_probability,
                prediction.neutral_probability,
                prediction.negative_probability,
                prediction.confidence,
                prediction.model_version,
            )
        except Exception as exc:
            with conn.cursor() as cursor:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT_NAME};")
            failed_count += 1
            logger.error(f"failed to persist sentiment result for review={review['review_id']}: {exc}")
        else:
            with conn.cursor() as cursor:
                cursor.execute(f"RELEASE SAVEPOINT {_SAVEPOINT_NAME};")
            if review.get("upgrade"):
                upgraded_count += 1
            else:
                analyzed_count += 1
    # Re-reading a review the plan already paid for is not counted again.
    if reservation is not None:
        usage.settle(conn, reservation, analyzed_count)
    conn.commit()

    logger.info(f"Classified {analyzed_count} reviews for tenant={tenant_id} ({upgraded_count} upgraded from star ratings, {failed_count} failed)")
    result = {"status": "OK", "analyzed_count": analyzed_count, "failed_count": failed_count, "method": method}
    if upgraded_count:
        result["upgraded_count"] = upgraded_count
    return result


def get_subject_sentiment_summary(
    conn,
    tenant_id: str,
    subject_type: str,
    subject_id: Optional[str] = None,
    country_context: Optional[str] = None,
) -> dict:
    aggregate = data_access.load_aggregate_sentiment(conn, tenant_id, subject_type, subject_id)
    sample_assessment = cold_start.assess(aggregate["analyzed_count"])

    if aggregate["analyzed_count"] == 0:
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
        logger.info(f"No analyzed reviews for tenant={tenant_id} subject={subject_type}/{subject_id}")
        return {"status": "UNKNOWN", "evidence_id": evidence_id, "sample_size": sample_assessment.as_dict()}

    if sample_assessment.sufficient:
        confidence_score = CONFIDENCE_SUFFICIENT_SAMPLE
        explanation = (
            f"Aggregated from {aggregate['analyzed_count']} analyzed reviews: "
            f"{aggregate['label_counts']['positive']} positive, {aggregate['label_counts']['neutral']} neutral, "
            f"{aggregate['label_counts']['negative']} negative (sentiment_score={aggregate['sentiment_score']})."
        )
    else:
        confidence_score = CONFIDENCE_LOW_SAMPLE
        explanation = (
            f"LOW SAMPLE SIZE: only {aggregate['analyzed_count']} analyzed review(s) available "
            f"(minimum {sample_assessment.minimum_required} required) - this result should not be treated as a "
            f"reliable market conclusion."
        )

    evidence_id = evidence.insert_evidence_record(
        conn,
        tenant_id,
        "FACT",
        SOURCE_MODULE,
        {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "analyzed_count": aggregate["analyzed_count"],
            "sentiment_score": aggregate["sentiment_score"],
        },
        confidence_score,
        explanation,
        None,
        country_context,
    )
    conn.commit()

    logger.info(
        f"Sentiment summary written tenant={tenant_id} subject={subject_type}/{subject_id} "
        f"status={sample_assessment.status} evidence_id={evidence_id}"
    )

    return {
        "status": "OK",
        "evidence_id": evidence_id,
        "sentiment_score": aggregate["sentiment_score"],
        "label_counts": aggregate["label_counts"],
        "sample_size": sample_assessment.as_dict(),
    }
