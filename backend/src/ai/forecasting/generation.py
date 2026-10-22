"""Shared per-product forecast generation and retry idempotency boundary."""

import os

from src.ai.forecasting import pipeline

STALE_AFTER_HOURS = float(os.getenv("FORECAST_STALE_AFTER_HOURS", "12"))


def generate_or_reuse_forecast(conn, tenant_id: str, product_id: str, horizon_days: int = 30, authorization_check=None) -> dict:
    """Serialize every generation path and reuse an eligible persisted result.

    The product lock is shared by the API, automatic refresh, and stream
    consumer, so page-load refresh cannot race an explicit generate request
    into duplicate history rows.
    """
    lock_key = f"keel:demand-forecast:{tenant_id}:{product_id}"
    if authorization_check:
        authorization_check()
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0));", (lock_key,))
        cursor.execute(
            """
            SELECT MAX(i.created_at)
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            WHERE ii.tenant_id = %s AND ii.product_id = %s AND i.payment_status <> 'CANCELLED';
            """,
            (tenant_id, product_id),
        )
        last_sale_at = cursor.fetchone()[0]
        if last_sale_at is None:
            cursor.execute(
                """
                SELECT evidence_id FROM evidence_records
                WHERE tenant_id = %s AND category = 'UNKNOWN' AND source_module = 'ai.forecasting'
                  AND source_record_ids->>'product_id' = %s
                  AND generated_at >= now() - make_interval(secs => %s)
                ORDER BY generated_at DESC LIMIT 1;
                """,
                (tenant_id, product_id, STALE_AFTER_HOURS * 3600),
            )
            prior_unknown = cursor.fetchone()
            if prior_unknown:
                conn.commit()
                return {"status": "UNKNOWN", "evidence_id": str(prior_unknown[0]), "reused": True}
        else:
            cursor.execute(
                """
                SELECT df.forecast_id, df.expected_demand, df.forecast_target_date, df.created_at,
                       df.features_used,
                       (SELECT er.evidence_id FROM evidence_records er
                        WHERE er.tenant_id = df.tenant_id AND er.source_module = 'ai.forecasting'
                          AND er.source_record_ids->>'forecast_id' = df.forecast_id::text
                        ORDER BY er.generated_at DESC LIMIT 1)
                FROM demand_forecasts df
                WHERE df.tenant_id = %s AND df.product_id = %s
                  AND df.created_at >= now() - make_interval(secs => %s)
                  AND df.created_at >= %s
                  AND COALESCE(df.features_used->>'horizon_days', '30') = %s
                ORDER BY df.created_at DESC LIMIT 1;
                """,
                (tenant_id, product_id, STALE_AFTER_HOURS * 3600, last_sale_at, str(horizon_days)),
            )
            row = cursor.fetchone()
            if row:
                forecast_id, expected, target, created_at, features, evidence_id = row
                features = features or {}
                conn.commit()
                return {
                    "status": "OK", "source": features.get("method"), "forecast_id": str(forecast_id),
                    "evidence_id": str(evidence_id) if evidence_id else None,
                    "expected_demand": float(expected), "horizon_days": horizon_days,
                    "forecast_target_date": target.isoformat(),
                    "confidence_score": features.get("confidence_score"),
                    "data_sufficiency": features.get("data_sufficiency"), "reused": True,
                    "last_successful_generation": created_at.isoformat(),
                }
    result = pipeline.run_forecast(conn, tenant_id, product_id, horizon_days, authorization_check=authorization_check)
    result["reused"] = False
    return result
