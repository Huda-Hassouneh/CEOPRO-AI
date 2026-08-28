"""
CEOPRO AI - Price Recommendation Evidence Writers.
Reuses insert_evidence_record from forecasting.evidence rather than
duplicating it - evidence_records is a shared, cross-module table (spec S22:
"Confidence must not be implemented independently by every AI module. The
system must have one consistent evidence architecture"), and the function is
already generic (not forecast-specific). Only recommendation_outcomes writing
is new here, since forecasting doesn't need it.
"""

from src.ai.forecasting.evidence import insert_evidence_record  # noqa: F401 (re-exported for pricing callers)


def insert_recommendation_outcome(conn, evidence_id: str, tenant_id: str, recommended_action: str) -> str:
    """
    Spec S24: "Every recommendation must create a RECOMMENDATION_OUTCOME
    record." Created at recommendation time with user_decision left to the
    table's default ('PENDING') - it's updated later when a human actually
    acts on the recommendation, which is outside this module's scope.

    recommended_action is Final_schema.sql's own column (a human-readable
    description of what's being recommended - e.g. "raise price to 18.50
    JOD") - forecasting-originated outcomes use forecast_id instead
    (nullable here); pricing's outcomes link back to evidence_id instead
    (also nullable on this table, added back via
    migrations/20260827040000_add_recommendation_outcomes_evidence_link.sql,
    since spec S24 requires this traceability and the schema didn't have it).
    """
    query = """
        INSERT INTO recommendation_outcomes (evidence_id, tenant_id, recommended_action)
        VALUES (%s, %s, %s)
        RETURNING recommendation_id;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, (evidence_id, tenant_id, recommended_action))
        recommendation_id = cursor.fetchone()[0]
    return str(recommendation_id)
