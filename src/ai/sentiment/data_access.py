"""
CEOPRO AI - Sentiment Analysis Data Access.
Reads reviews - owned by the review-collection service per
DATA_OWNERSHIP_AND_CONTRACTS.md, this module only reads from it. Writes
only to sentiment_results/evidence_records, this track's own tables
(handled in evidence.py).
"""

from typing import Optional

import psycopg2


def load_unanalyzed_reviews(conn: "psycopg2.extensions.connection", tenant_id: str, limit: int = 100) -> list:
    """
    Reviews with no matching sentiment_results row yet, restricted to
    ALLOWED-source reviews with non-empty text - a RESTRICTED/BLOCKED review
    (spec S13's Collection Policy Engine) shouldn't silently feed a model.
    """
    query = """
        SELECT r.review_id, r.review_text, r.subject_type, r.product_id, r.competitor_id, r.review_language
        FROM reviews r
        LEFT JOIN sentiment_results sr ON sr.review_id = r.review_id
        WHERE r.tenant_id = %s
          AND sr.sentiment_id IS NULL
          AND r.source_status = 'ALLOWED'
          AND COALESCE(r.safety_status, 'SAFE') = 'SAFE'
          AND r.review_text IS NOT NULL
          AND length(trim(r.review_text)) > 0
        ORDER BY r.review_date
        LIMIT %s;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, (tenant_id, limit))
        rows = cursor.fetchall()

    return [
        {
            "review_id": str(row[0]),
            "review_text": row[1],
            "subject_type": row[2],
            "product_id": str(row[3]) if row[3] else None,
            "competitor_id": str(row[4]) if row[4] else None,
            "review_language": row[5],
        }
        for row in rows
    ]


def load_aggregate_sentiment(
    conn: "psycopg2.extensions.connection", tenant_id: str, subject_type: str, subject_id: Optional[str] = None
) -> dict:
    """
    Aggregates already-analyzed sentiment_results for one subject: a
    label -> count breakdown plus the continuous sentiment score spec S16
    allows (avg(positive_probability) - avg(negative_probability), weighted
    by each label group's count) across all analyzed reviews for that
    subject. subject_id is ignored (and must be None) for BUSINESS, since
    that reads overall business-level reviews.
    """
    if subject_type == "BUSINESS":
        subject_filter = ""
        params = [tenant_id, subject_type]
    elif subject_type == "PRODUCT":
        subject_filter = "AND r.product_id = %s"
        params = [tenant_id, subject_type, subject_id]
    elif subject_type == "COMPETITOR":
        subject_filter = "AND r.competitor_id = %s"
        params = [tenant_id, subject_type, subject_id]
    else:
        raise ValueError(f"Unknown subject_type '{subject_type}'")

    # sentiment_results.sentiment_label stores upper-case labels (Final_schema.sql's
    # own convention, CHECK (sentiment_label IN ('POSITIVE','NEUTRAL','NEGATIVE')));
    # lower-cased here so this module's internal convention (used throughout
    # cold_start.py/model.py/pipeline.py) doesn't need to change.
    query = f"""
        SELECT LOWER(sr.sentiment_label), COUNT(*), AVG(sr.positive_probability), AVG(sr.negative_probability)
        FROM reviews r
        JOIN sentiment_results sr ON sr.review_id = r.review_id
        WHERE r.tenant_id = %s AND r.subject_type = %s {subject_filter}
        GROUP BY sr.sentiment_label;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()

    label_counts = {"positive": 0, "neutral": 0, "negative": 0}
    weighted_pos_sum = 0.0
    weighted_neg_sum = 0.0
    total = 0
    for label, count, avg_pos, avg_neg in rows:
        label_counts[label] = int(count)
        total += int(count)
        weighted_pos_sum += float(avg_pos) * int(count)
        weighted_neg_sum += float(avg_neg) * int(count)

    sentiment_score = round((weighted_pos_sum - weighted_neg_sum) / total, 4) if total else None

    return {
        "analyzed_count": total,
        "label_counts": label_counts,
        "sentiment_score": sentiment_score,
    }


def load_aggregate_sentiment_by_competitor(
    conn: "psycopg2.extensions.connection", tenant_id: str
) -> dict:
    """
    Same aggregate load_aggregate_sentiment(subject_type="COMPETITOR")
    computes, but for EVERY tracked competitor in one round trip
    (GROUP BY competitor_id, sentiment_label) instead of one query per
    competitor. Built for structured_summaries.py::
    generate_sentiment_trends_summary(), which previously called
    sentiment/pipeline.py::get_subject_sentiment_summary() once per
    tracked competitor - a real N+1 (dozens of round trips for a tenant
    tracking dozens of competitors, on every RAG summary regeneration).

    Returns {competitor_id (str): {"analyzed_count", "label_counts",
    "sentiment_score"}} - same per-subject shape load_aggregate_sentiment()
    returns, just keyed by competitor_id. A competitor with no analyzed
    reviews at all simply has no key here (matches load_aggregate_sentiment's
    own "zero-signal" case: analyzed_count=0, sentiment_score=None) - the
    caller treats a missing key the same way it would treat that result.

    Deliberately bypasses get_subject_sentiment_summary() and its
    evidence_records writes: those are the right side effect for a
    single, user-facing "what's this competitor's sentiment" query, but
    not for a background narrative-summary regeneration loop that would
    otherwise write one UNKNOWN/FACT evidence row per tracked competitor
    on every single regeneration - structured_summaries.py's other
    generators already query sentiment_results/reviews directly for the
    same reason.
    """
    query = """
        SELECT r.competitor_id, LOWER(sr.sentiment_label), COUNT(*),
               AVG(sr.positive_probability), AVG(sr.negative_probability)
        FROM reviews r
        JOIN sentiment_results sr ON sr.review_id = r.review_id
        WHERE r.tenant_id = %s AND r.subject_type = 'COMPETITOR' AND r.competitor_id IS NOT NULL
        GROUP BY r.competitor_id, sr.sentiment_label;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, (tenant_id,))
        rows = cursor.fetchall()

    by_competitor: dict = {}
    for competitor_id, label, count, avg_pos, avg_neg in rows:
        entry = by_competitor.setdefault(
            str(competitor_id),
            {"label_counts": {"positive": 0, "neutral": 0, "negative": 0}, "_weighted_pos": 0.0, "_weighted_neg": 0.0, "_total": 0},
        )
        entry["label_counts"][label] = int(count)
        entry["_total"] += int(count)
        entry["_weighted_pos"] += float(avg_pos) * int(count)
        entry["_weighted_neg"] += float(avg_neg) * int(count)

    results = {}
    for competitor_id, entry in by_competitor.items():
        total = entry["_total"]
        sentiment_score = round((entry["_weighted_pos"] - entry["_weighted_neg"]) / total, 4) if total else None
        results[competitor_id] = {
            "analyzed_count": total,
            "label_counts": entry["label_counts"],
            "sentiment_score": sentiment_score,
        }
    return results
