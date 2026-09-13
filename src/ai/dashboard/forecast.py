"""
CEOPRO AI - Dashboard Forecast KPI (presentation layer, not a new model).

forecasting/pipeline.py::run_forecast() already returns exactly what the
guardrail requires - a single integer, expected_demand, per product per
call - and nothing here changes that signature or shape. The dashboard
mockup's forecast chart just needs one number for the whole business, not
a per-product breakdown, so this reads the most recent persisted forecast
row per product (demand_forecasts, the same table/column shape
insights/pipeline.py::_load_latest_forecasts() already reads for the
insights engine) and sums them into one KPI.

A product with no forecast yet (never run, or the consumer hasn't
processed a request for it) simply doesn't contribute to the sum - not
treated as a zero-demand forecast, since that would be fabricating a
number no model ever produced.
"""
def get_forecast_summary(conn, tenant_id: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (df.product_id)
                df.product_id, df.expected_demand, df.forecast_target_date
            FROM demand_forecasts df
            WHERE df.tenant_id = %s
            ORDER BY df.product_id, df.created_at DESC;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    total_predicted_units = sum(int(expected_demand) for _product_id, expected_demand, _target_date in rows)
    latest_target_date = max(
        (target_date for _product_id, _expected_demand, target_date in rows if target_date is not None),
        default=None,
    )

    return {
        "total_predicted_units": total_predicted_units,
        "products_forecasted": len(rows),
        "forecast_target_date": latest_target_date.isoformat() if latest_target_date else None,
    }
