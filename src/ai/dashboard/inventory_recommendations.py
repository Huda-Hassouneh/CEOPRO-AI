"""
CEOPRO AI - Dashboard Inventory Recommendations (presentation layer, not
a new model, no new tables).

The mockup's "Priority Inventory Actions"/"Inventory Recommendations"
tables. Rule-based, not a learned model - same "transparent, explainable
weighted rule" discipline pricing/recommendation.py already applies to
price suggestions (spec S19: a learned model needs historical outcome
data this platform doesn't have yet for pricing, and doesn't have for
inventory actions either). RESTOCK_NOW/REDUCE_ORDER is decided purely
from (predicted 30-day demand vs. current real stock) - the same real
comparison forecast_movers.py computes - never from an invented "AI
reasoning" narrative ("strong demand interest expected", "seasonal peak")
the way the mockup's own "Reason" column suggests: this module's reason
text is built entirely from the real numbers behind the decision, nothing
guessed about WHY demand is moving.

suggested_qty = predicted_demand - current_stock, signed (positive = order
more, negative = reduce). estimated_revenue_impact is only ever computed
for a RESTOCK_NOW row (the real revenue at stake if that demand is met)
using products.current_price, which is NOT NULL for every real product -
never a profit figure, since cost_price is frequently unset and a real
NULL cost must never be silently treated as zero.

model_accuracy_pct joins evidence_records via source_record_ids->>
'forecast_id' rather than the forecast_id column - see forecast_detail.py's
own docstring for the real, previously-undiscovered bug this fixes
(evidence_records.forecast_id is never actually populated).
"""
DEFAULT_LIMIT = 20

ACTION_RESTOCK_NOW = "RESTOCK_NOW"
ACTION_REDUCE_ORDER = "REDUCE_ORDER"
ACTION_MONITOR = "MONITOR"

# Mirrors forecast_movers.py's own STABLE_BAND_PCT - the same +-20% band
# that keeps ordinary forecast noise from being flagged as an action.
ACTION_THRESHOLD_PCT = 20.0
# Beyond this gap, the action is urgent enough to call High priority
# rather than Medium - a second, wider band on the same real number, not
# a second invented signal.
HIGH_PRIORITY_THRESHOLD_PCT = 50.0


def _priority_for_gap(change_pct: float) -> str:
    return "High" if abs(change_pct) >= HIGH_PRIORITY_THRESHOLD_PCT else "Medium"


def get_inventory_recommendations(conn, tenant_id: str, limit: int = DEFAULT_LIMIT) -> dict:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (df.product_id)
                df.product_id,
                COALESCE(p.product_name->>'en', p.product_name->>'ar', p.product_name::text) AS product_name,
                p.category->>'en' AS category, p.current_price, p.currency,
                i.stock_quantity, df.expected_demand, df.forecast_target_date, er.confidence_score
            FROM demand_forecasts df
            JOIN products p ON p.tenant_id = df.tenant_id AND p.product_id = df.product_id
            JOIN inventory i ON i.tenant_id = df.tenant_id AND i.product_id = df.product_id
            LEFT JOIN evidence_records er ON er.tenant_id = df.tenant_id
                AND er.source_module = 'ai.forecasting'
                AND (er.source_record_ids->>'forecast_id')::uuid = df.forecast_id
            WHERE df.tenant_id = %s AND p.deleted_at IS NULL AND i.stock_quantity > 0
            ORDER BY df.product_id, df.created_at DESC;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()

    recommendations = []
    for product_id, name, category, current_price, currency, stock, expected_demand, target_date, confidence_score in rows:
        stock = int(stock)
        expected_demand = float(expected_demand)
        current_price = float(current_price)
        change_pct = round((expected_demand - stock) / stock * 100, 1)
        suggested_qty = round(expected_demand - stock)

        if change_pct >= ACTION_THRESHOLD_PCT:
            action = ACTION_RESTOCK_NOW
            reason = f"Predicted 30-day demand ({round(expected_demand)} units) exceeds current stock ({stock} units) by {change_pct:.0f}%."
            estimated_revenue_impact = round(suggested_qty * current_price, 2)
        elif change_pct <= -ACTION_THRESHOLD_PCT:
            action = ACTION_REDUCE_ORDER
            reason = f"Predicted 30-day demand ({round(expected_demand)} units) is {abs(change_pct):.0f}% below current stock ({stock} units)."
            estimated_revenue_impact = None
        else:
            action = ACTION_MONITOR
            reason = f"Predicted 30-day demand ({round(expected_demand)} units) is within normal range of current stock ({stock} units)."
            estimated_revenue_impact = None

        recommendations.append({
            "product_id": str(product_id),
            "product_name": name,
            "category": category,
            "current_stock": stock,
            "predicted_demand": round(expected_demand),
            "forecast_target_date": target_date.isoformat(),
            "action": action,
            "suggested_qty": suggested_qty,
            "priority": _priority_for_gap(change_pct) if action != ACTION_MONITOR else "Low",
            "reason": reason,
            "model_accuracy_pct": round(float(confidence_score) * 100) if confidence_score is not None else None,
            "estimated_revenue_impact": estimated_revenue_impact,
            "currency": currency,
        })

    recommendations.sort(key=lambda r: (r["action"] != ACTION_RESTOCK_NOW, -abs(r["suggested_qty"])))

    return {
        "restock_now_count": sum(1 for r in recommendations if r["action"] == ACTION_RESTOCK_NOW),
        "reduce_order_count": sum(1 for r in recommendations if r["action"] == ACTION_REDUCE_ORDER),
        "monitor_count": sum(1 for r in recommendations if r["action"] == ACTION_MONITOR),
        "recommendations": recommendations[:limit],
    }
