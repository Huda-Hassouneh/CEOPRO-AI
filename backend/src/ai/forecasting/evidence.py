"""
KEEL - Demand Forecasting Evidence Writers.
Writes only to tables this track owns per DATA_OWNERSHIP_AND_CONTRACTS.md:
demand_forecasts, evidence_records, model_versions. Never writes to tables
owned by other services.
"""

import json
import math
from datetime import date
from typing import Optional


def insert_demand_forecast(
    conn,
    tenant_id: str,
    product_id: str,
    expected_demand: float,
    confidence_range_lower: Optional[float],
    confidence_range_upper: Optional[float],
    forecast_target_date: date,
    model_version: str,
    forecast_start_date: Optional[date] = None,
    features_used: Optional[dict] = None,
) -> str:
    """features_used carries the day-by-day forecast ("daily") and how it was
    produced ("method"), so screens can chart the real forecast path."""
    query = """
        INSERT INTO demand_forecasts
            (tenant_id, product_id, expected_demand, confidence_range_lower,
             confidence_range_upper, forecast_target_date, model_version,
             forecast_start_date, forecast_end_date, features_used)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING forecast_id;
    """
    with conn.cursor() as cursor:
        cursor.execute(
            query,
            (
                tenant_id,
                product_id,
                int(round(expected_demand)),
                int(round(confidence_range_lower)) if confidence_range_lower is not None else None,
                int(round(confidence_range_upper)) if confidence_range_upper is not None else None,
                forecast_target_date,
                model_version,
                forecast_start_date,
                forecast_target_date if forecast_start_date else None,
                json.dumps(_json_safe(features_used or {})),
            ),
        )
        forecast_id = cursor.fetchone()[0]
    return str(forecast_id)


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


def _json_safe(value):
    """NaN/Infinity aren't valid JSON (Postgres rejects them). They occur for
    real: a product that sells the same quantity every day has a MASE of
    0/0. Stored as null instead of failing the whole forecast."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def insert_model_version(conn, model_name: str, version: str, status: str, metrics: dict) -> str:
    query = """
        INSERT INTO model_versions (model_name, version, status, trained_at, metrics)
        VALUES (%s, %s, %s, NOW(), %s::jsonb)
        RETURNING model_version_id;
    """
    with conn.cursor() as cursor:
        cursor.execute(query, (model_name, version, status, json.dumps(_json_safe(metrics))))
        model_version_id = cursor.fetchone()[0]
    return str(model_version_id)
