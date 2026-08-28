"""
CEOPRO AI - MPI Data Access.
Reads reviews joined with their already-analyzed sentiment_results
(read-only, both owned by other pipelines - reviews by the review-collection
service, sentiment_results written by src/ai/sentiment/). Row-level, unlike
sentiment/data_access.py's pre-aggregated load_aggregate_sentiment(), because
the MPI needs each review's own date/collection_method to compute per-review
recency/reliability weights (spec S17).
"""

from typing import Optional

import psycopg2


def load_scored_reviews(
    conn: "psycopg2.extensions.connection", tenant_id: str, subject_type: str, subject_id: Optional[str] = None
) -> list:
    """
    Only reviews that already have a sentiment_results row - an unanalyzed
    review contributes nothing to the MPI yet (run
    sentiment.pipeline.classify_and_store_reviews first). subject_id is
    ignored (and must be None) for BUSINESS.
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

    # sentiment_results.sentiment_label is upper-case (Final_schema.sql's own
    # convention) - lower-cased here so this module's internal convention
    # (matching sentiment/'s) doesn't need to change. reviews has no
    # collected_at column anymore, only review_date (NOT NULL), so no
    # COALESCE fallback is needed.
    query = f"""
        SELECT sr.review_id, LOWER(sr.sentiment_label), sr.positive_probability, sr.negative_probability,
               r.review_date AS effective_date, r.collection_method
        FROM reviews r
        JOIN sentiment_results sr ON sr.review_id = r.review_id
        WHERE r.tenant_id = %s AND r.subject_type = %s {subject_filter};
    """
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()

    return [
        {
            "review_id": str(row[0]),
            "label": row[1],
            "positive_probability": float(row[2]) if row[2] is not None else 0.0,
            "negative_probability": float(row[3]) if row[3] is not None else 0.0,
            "effective_date": row[4].date() if row[4] is not None else None,
            "collection_method": row[5],
        }
        for row in rows
    ]


def load_country_context(
    conn: "psycopg2.extensions.connection", tenant_id: str, subject_type: str, subject_id: Optional[str] = None
) -> Optional[str]:
    """
    BUSINESS/PRODUCT use the tenant's own country - products has no
    country_code column of its own (PENDING_ACTIONS.md doesn't track this as
    blocking anything today, but it means a product sold in a second
    operating_country still reports the tenant's primary country here).
    COMPETITOR uses the competitor's own country_code, which may be NULL.
    """
    if subject_type in ("BUSINESS", "PRODUCT"):
        query = "SELECT country_code FROM companies WHERE tenant_id = %s;"
        params = (tenant_id,)
    elif subject_type == "COMPETITOR":
        # subject_id is a global_competitor_id (what reviews.competitor_id
        # actually stores - see migrations/20260827010000_restore_review_subject_types.sql).
        # Joined through tenant_competitors, not queried directly against
        # global_competitors, so a competitor_id belonging to a different
        # tenant's PRIVATE competitor can't leak a country_code back here.
        query = """
            SELECT gc.country_code
            FROM tenant_competitors tc
            JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.global_competitor_id = %s;
        """
        params = (tenant_id, subject_id)
    else:
        raise ValueError(f"Unknown subject_type '{subject_type}'")

    with conn.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()

    return row[0] if row else None
