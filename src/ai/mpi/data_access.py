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

    query = f"""
        SELECT sr.review_id, sr.label, sr.positive_probability, sr.negative_probability,
               COALESCE(r.review_date, r.collected_at) AS effective_date, r.collection_method
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
        query = "SELECT country_code FROM competitors WHERE tenant_id = %s AND competitor_id = %s;"
        params = (tenant_id, subject_id)
    else:
        raise ValueError(f"Unknown subject_type '{subject_type}'")

    with conn.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()

    return row[0] if row else None
