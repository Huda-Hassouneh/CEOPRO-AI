"""
KEEL - MPI Data Access.
Reads reviews joined with their already-analyzed sentiment_results
(read-only, both owned by other pipelines - reviews by the review-collection
service, sentiment_results written by src/ai/sentiment/). Row-level, unlike
sentiment/data_access.py's pre-aggregated load_aggregate_sentiment(), because
the MPI needs each review's own date/collection_method to compute per-review
recency/reliability weights (spec S17).
"""

import math
import uuid
from typing import Optional

import psycopg2


class InvalidSubjectType(ValueError):
    """The requested MPI scope is not one of the three supported scopes."""


class InvalidSubjectIdentifier(ValueError):
    """The requested scope has a malformed or inconsistent identifier."""


class SubjectNotFoundError(LookupError):
    """The subject is absent or is not visible to the authenticated tenant."""


SUPPORTED_SUBJECT_TYPES = {"BUSINESS", "PRODUCT", "COMPETITOR"}


def load_history(
    conn, tenant_id: str, source_module: str, subject_type: str,
    canonical_subject: Optional[str], limit: int, offset: int,
) -> list:
    """Read existing evidence rows after subject validation; do not commit."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT evidence_id,generated_at,source_record_ids,confidence_score,explanation_text FROM evidence_records WHERE tenant_id=%s AND source_module=%s AND source_record_ids->>'subject_type'=%s AND (source_record_ids->>'subject_id' IS NOT DISTINCT FROM %s OR (%s='BUSINESS' AND source_record_ids->>'subject_id'=%s)) ORDER BY generated_at DESC,evidence_id DESC LIMIT %s OFFSET %s",(tenant_id,source_module,subject_type,canonical_subject,subject_type,tenant_id,limit,offset))
        return cursor.fetchall()


def validate_subject(
    conn: "psycopg2.extensions.connection", tenant_id: str, subject_type: str,
    subject_id: Optional[str] = None,
) -> None:
    """Validate scope identity and tenant ownership before any MPI evidence write."""
    if subject_type not in SUPPORTED_SUBJECT_TYPES:
        raise InvalidSubjectType("Unsupported MPI subject type.")

    if subject_type == "BUSINESS":
        # The canonical BUSINESS identity is the authenticated tenant itself.
        if subject_id is not None and str(subject_id) != str(tenant_id):
            raise SubjectNotFoundError("MPI subject not found.")
        query = "SELECT 1 FROM companies WHERE tenant_id = %s AND deleted_at IS NULL;"
        params = (tenant_id,)
    else:
        try:
            canonical_id = str(uuid.UUID(str(subject_id)))
        except (TypeError, ValueError, AttributeError):
            raise InvalidSubjectIdentifier("A valid subject identifier is required.") from None

        if subject_type == "PRODUCT":
            query = """
                SELECT 1 FROM products
                WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;
            """
            params = (tenant_id, canonical_id)
        else:
            # A competitor is visible to MPI only through this tenant's
            # established tenant_competitors relationship.  The join also
            # keeps private competitor metadata tenant-scoped.
            query = """
                SELECT 1
                FROM tenant_competitors tc
                JOIN global_competitors gc
                  ON gc.global_competitor_id = tc.global_competitor_id
                WHERE tc.tenant_id = %s AND tc.global_competitor_id = %s;
            """
            params = (tenant_id, canonical_id)

    with conn.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
    if row is None:
        raise SubjectNotFoundError("MPI subject not found.")


def load_scored_reviews(
    conn: "psycopg2.extensions.connection", tenant_id: str, subject_type: str,
    subject_id: Optional[str] = None,
) -> list:
    """
    Only analyzed, allowed, safe, nonblank reviews dated no later than the
    database clock are eligible. Subject ownership is checked by
    ``validate_subject`` before this query is called.
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
               r.review_date AS effective_date, r.collection_method, r.source_platform,
               r.source_id, sr.model_version
        FROM reviews r
        JOIN sentiment_results sr
          ON sr.review_id = r.review_id AND sr.tenant_id = r.tenant_id
        WHERE r.tenant_id = %s AND r.subject_type = %s
          AND r.source_status = 'ALLOWED'
          AND r.safety_status = 'SAFE'
          AND BTRIM(r.review_text) <> ''
          AND r.review_date <= CURRENT_TIMESTAMP
          AND (
              r.source_id IS NULL OR EXISTS (
                  SELECT 1 FROM data_sources ds
                  WHERE ds.tenant_id = r.tenant_id AND ds.source_id = r.source_id
              )
          )
          {subject_filter}
        ORDER BY r.review_date DESC, r.review_id;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()

    reviews = []
    seen_review_ids = set()
    for row in rows:
        review_id = str(row[0])
        # The schema already enforces one sentiment row per review; this
        # defensive identity check also prevents duplicate contributions if
        # a future join is widened.
        if review_id in seen_review_ids:
            continue
        try:
            positive = float(row[2])
            negative = float(row[3])
        except (TypeError, ValueError, OverflowError):
            continue
        if not (math.isfinite(positive) and math.isfinite(negative)):
            continue
        if not (0.0 <= positive <= 1.0 and 0.0 <= negative <= 1.0):
            continue
        if row[1] not in {"positive", "neutral", "negative"} or row[4] is None:
            continue
        seen_review_ids.add(review_id)
        reviews.append({
            "review_id": review_id,
            "label": row[1],
            "positive_probability": positive,
            "negative_probability": negative,
            "effective_date": row[4].date() if hasattr(row[4], "date") else row[4],
            "collection_method": row[5],
            "source_platform": row[6],
            "source_id": str(row[7]) if row[7] is not None else None,
            "sentiment_model_version": row[8],
        })
    return reviews


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
