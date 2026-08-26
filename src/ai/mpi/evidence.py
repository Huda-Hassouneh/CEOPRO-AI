"""
CEOPRO AI - MPI Evidence Writer.
No dedicated MPI table exists in the schema (checked - there isn't one), so
results are written purely to evidence_records, per spec S22's shared
evidence architecture: an MPI is exactly the kind of derived FACT that
architecture exists for, not a new bespoke table.
"""

import json
from typing import Optional


def insert_evidence_record(
    conn,
    tenant_id: str,
    category: str,
    source_module: str,
    source_record_ids: dict,
    confidence_score: Optional[float],
    explanation_text: str,
    model_version: Optional[str],
    country_context: Optional[str] = None,
) -> str:
    query = """
        INSERT INTO evidence_records
            (tenant_id, category, source_module, source_record_ids,
             confidence_score, explanation_text, model_version, country_context)
        VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
        RETURNING evidence_id;
    """
    with conn.cursor() as cursor:
        cursor.execute(
            query,
            (
                tenant_id,
                category,
                source_module,
                json.dumps(source_record_ids),
                confidence_score,
                explanation_text,
                model_version,
                country_context,
            ),
        )
        evidence_id = cursor.fetchone()[0]
    return str(evidence_id)
