"""
CEOPRO AI - Dashboard Product Forecast Detail (presentation layer, not a
new model, no new tables).

The mockup's product-level forecast page (current stock, predicted
demand, model accuracy, average daily demand, confidence interval,
forecast history). Every field here is a real, already-persisted value -
no invented "AI Insight" narrative, no seasonality heatmap (nothing in
this codebase computes seasonal decomposition), no "Estimated Revenue
Opportunity" causal story - see forecast_movers.py/inventory_
recommendations.py for the two real, honest financial-impact numbers
this platform can compute today.

model_accuracy_pct is evidence_records.confidence_score (forecasting/
pipeline.py's own MASE-derived 0.3-0.95 confidence, rescaled to a
percentage) - the same number structured_summaries.py's own
_plain_confidence_label() already translates for the chatbot, just kept
numeric here since a dashboard card (unlike chat prose) is the right
place for a plain percentage, not the raw MASE/RMSE statistic itself.

Real bug fix discovered while building this: evidence_records.forecast_id
is NEVER actually set for a forecasting evidence row - forecasting/
pipeline.py::run_forecast() writes the real forecast_id inside
source_record_ids (a JSONB blob: {"forecast_id": ..., "product_id": ...}),
not the forecast_id column, which stays NULL. Joining on
`er.forecast_id = df.forecast_id` (what structured_summaries.py's own
generate_demand_forecast_summary() has always done) can therefore never
match anything - confidence_score has silently been NULL there since
that code shipped. Fixed here by joining on the real location
(source_record_ids->>'forecast_id'); see this same fix applied to
structured_summaries.py in this same change.

forecast_history is every real forecast run this platform has ever
persisted for this product (demand_forecasts, oldest first) - not a
fabricated monthly table, since this platform's forecasting produces one
forecast per real run, not a rolling 6-month schedule.
"""
DEFAULT_HISTORY_LIMIT = 20


def get_product_forecast_detail(conn, tenant_id: str, product_id: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS name,
                   p.category->>'en' AS category, p.current_price, p.currency, i.stock_quantity
            FROM products p
            LEFT JOIN inventory i ON i.tenant_id = p.tenant_id AND i.product_id = p.product_id
            WHERE p.tenant_id = %s AND p.product_id = %s AND p.deleted_at IS NULL;
            """,
            (tenant_id, product_id),
        )
        product_row = cursor.fetchone()
        if product_row is None:
            return None
        name, category, current_price, currency, stock_quantity = product_row

        cursor.execute(
            """
            SELECT COALESCE(SUM(ii.quantity), 0), COUNT(DISTINCT i.issue_date::date)
            FROM invoice_items ii
            JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
            WHERE ii.tenant_id = %s AND ii.product_id = %s AND i.issue_date >= NOW() - INTERVAL '90 days';
            """,
            (tenant_id, product_id),
        )
        units_sold_90d, days_with_sales = cursor.fetchone()

        cursor.execute(
            """
            SELECT df.expected_demand, df.confidence_range_lower, df.confidence_range_upper,
                   df.forecast_target_date, df.model_version, df.created_at, er.confidence_score
            FROM demand_forecasts df
            LEFT JOIN evidence_records er ON er.tenant_id = df.tenant_id
                AND er.source_module = 'ai.forecasting'
                AND (er.source_record_ids->>'forecast_id')::uuid = df.forecast_id
            WHERE df.tenant_id = %s AND df.product_id = %s
            ORDER BY df.created_at DESC
            LIMIT %s;
            """,
            (tenant_id, product_id, DEFAULT_HISTORY_LIMIT),
        )
        forecast_rows = cursor.fetchall()

    avg_daily_demand = round(float(units_sold_90d) / 90, 1)

    if not forecast_rows:
        latest_forecast = None
    else:
        expected_demand, lower, upper, target_date, model_version, created_at, confidence_score = forecast_rows[0]
        latest_forecast = {
            "predicted_demand": round(float(expected_demand)),
            "confidence_range_lower": round(float(lower)) if lower is not None else None,
            "confidence_range_upper": round(float(upper)) if upper is not None else None,
            "forecast_target_date": target_date.isoformat(),
            "model_version": model_version,
            "model_accuracy_pct": round(float(confidence_score) * 100) if confidence_score is not None else None,
        }

    return {
        "product_id": product_id,
        "product_name": name,
        "category": category,
        "current_price": float(current_price),
        "currency": currency,
        "current_stock": int(stock_quantity) if stock_quantity is not None else None,
        "avg_daily_demand": avg_daily_demand,
        "latest_forecast": latest_forecast,
        "forecast_history": [
            {
                "predicted_demand": round(float(expected_demand)),
                "confidence_range_lower": round(float(lower)) if lower is not None else None,
                "confidence_range_upper": round(float(upper)) if upper is not None else None,
                "forecast_target_date": target_date.isoformat(),
                "created_at": created_at.isoformat(),
            }
            for expected_demand, lower, upper, target_date, _model_version, created_at, _confidence_score in forecast_rows
        ],
    }
