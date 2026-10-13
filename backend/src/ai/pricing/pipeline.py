"""
KEEL - Price Recommendation Pipeline (spec S9, S19, S20, S22, S23, S24).
Orchestrates: load own product -> load same-currency competitor prices ->
rule-based recommendation -> price-change guardrail -> margin guardrail ->
persist evidence + recommendation_outcomes. Only module here that writes to
the database.

No name-matching step anymore (matching.py is no longer used in this path) -
Final_schema.sql's competitor_product_mappings resolves a competitor price to
a specific product_id at mapping-creation time, not query time, so
data_access.load_competitor_prices() already returns exactly this product's
competitor prices via a real FK join. See data_access.py's module docstring.
"""

import logging

from src.ai.core.money import format_money
from src.ai.pricing import currency, data_access, evidence, guardrails, recommendation

logger = logging.getLogger("CEOPRO_AI_PRICING_PIPELINE")

SOURCE_MODULE = "ai.pricing"


def _build_cross_currency_reference(conn, tenant_id: str, product_id: str, own_currency: str) -> str:
    """
    Spec S19: "The system must NOT use a simple currency conversion as the
    only basis for a cross-country pricing recommendation" - this is
    reference information appended to the explanation text, never blended
    into recommendation.py's market_avg/action math. Returns "" if there's
    nothing to report (no cross-currency prices for this product, or none
    with an available rate) rather than a sentence claiming there's nothing
    to see.
    """
    cross_currency_prices = data_access.load_cross_currency_competitor_prices(conn, tenant_id, product_id, own_currency)
    if not cross_currency_prices:
        return ""

    converted_parts = []
    unconverted_currencies = set()
    for record in cross_currency_prices:
        result = currency.convert(conn, record["price_found"], record["currency"], own_currency)
        if result is None:
            unconverted_currencies.add(record["currency"])
            continue
        converted_parts.append(
            f"{format_money(record['price_found'], record['currency'])} {record['currency']} -> "
            f"{format_money(result.converted_amount, own_currency)} {own_currency} "
            f"(rate {result.rate:.4f} as of {result.rate_date.isoformat()})"
        )

    if not converted_parts and not unconverted_currencies:
        return ""

    note = " For cross-country reference only (not used in this recommendation, per policy - currency conversion" \
           " alone doesn't account for purchasing power, taxes, or import cost differences between markets):"
    if converted_parts:
        note += " " + "; ".join(converted_parts) + "."
    if unconverted_currencies:
        note += (
            f" No current exchange rate available for {', '.join(sorted(unconverted_currencies))} -> "
            f"{own_currency}, so those competitor prices couldn't be converted for reference."
        )
    return note


HORIZON_DAYS = 30
DEMAND_SHIFT_PCT = 15.0
DEMAND_MIN_UNITS = 10.0


def _qty(value) -> str:
    value = float(value or 0)
    return f"{value:.0f}" if abs(value - round(value)) < 0.05 else f"{value:.1f}"


def _demand_context(conn, tenant_id: str, product_id: str):
    """This product's sales, forecast and stock - the same numbers the Demand
    screen shows (forecasting/overview.py). None when it can't be read."""
    try:
        from src.ai.forecasting import overview

        data = overview.build_overview(conn, tenant_id, product_id=product_id)
    except Exception:  # noqa: BLE001 - pricing still works without demand context
        logger.exception("demand context unavailable for pricing (tenant=%s product=%s)", tenant_id, product_id)
        return None
    row = next((p for p in data.get("products", []) if p.get("product_id") == str(product_id)), None)
    if row is None:
        return None
    return {
        "sold_last_30": row.get("sold_last_30"),
        "sold_previous_30": row.get("sold_previous_30") or 0,
        "sales_change_pct": row.get("sales_change_pct"),
        "forecast_next_30": row.get("forecast_next_30"),
        "trend": row.get("trend"),
        "stock": row.get("current_stock"),
        "stock_action": row.get("stock_action"),
        "days_of_cover": row.get("stock_days_of_cover"),
    }


class ProductNotFoundError(ValueError):
    """The product doesn't exist for this tenant (unknown id, or another
    tenant's product hidden by RLS). A ValueError subclass so existing
    callers that catch ValueError keep working; the API maps it to 404."""


def run_price_recommendation(conn, tenant_id: str, product_id: str) -> dict:
    own = data_access.load_own_product(conn, tenant_id, product_id)
    if own is None:
        raise ProductNotFoundError(f"No product found for tenant={tenant_id} product_id={product_id}")

    competitor_prices = data_access.load_competitor_prices(conn, tenant_id, product_id, own["currency"])
    cross_currency_note = _build_cross_currency_reference(conn, tenant_id, product_id, own["currency"])

    if not competitor_prices:
        explanation = (
            f"No competitor prices for '{own['product_name']}' in {own['currency']} were recorded in the last "
            f"{data_access.MAX_PRICE_AGE_DAYS} days."
        ) + cross_currency_note
        evidence_id = evidence.insert_evidence_record(
            conn, tenant_id, "UNKNOWN", SOURCE_MODULE, {"product_id": product_id}, None, explanation, None
        )
        conn.commit()
        logger.info(f"No competitor prices for tenant={tenant_id} product={product_id}; evidence={evidence_id}")
        return {"status": "UNKNOWN", "explanation": explanation, "evidence_id": evidence_id,
                "max_price_age_days": data_access.MAX_PRICE_AGE_DAYS}

    own_currency = own["currency"]
    money = lambda amount: format_money(amount, own_currency)  # noqa: E731
    rec = recommendation.build_recommendation(own["current_price"], competitor_prices, own_currency)
    change_guardrail = guardrails.apply_price_change_guardrail(
        own["current_price"], rec.raw_suggested_price, currency=own_currency
    )
    final_suggested_price = change_guardrail.suggested_price

    explanation = rec.explanation
    if change_guardrail.clamped:
        explanation += (
            f" Suggested price {money(rec.raw_suggested_price)} was outside the "
            f"{change_guardrail.max_change_pct:.0%} price-change guardrail and was capped to "
            f"{money(change_guardrail.suggested_price)}."
        )

    margin_guardrail = guardrails.apply_margin_guardrail(own["cost"], final_suggested_price, currency=own_currency)
    if margin_guardrail is not None:
        final_suggested_price = margin_guardrail.suggested_price
        if margin_guardrail.clamped:
            explanation += (
                f" Suggested price {money(change_guardrail.suggested_price)} was below the minimum-margin floor "
                f"{money(margin_guardrail.floor_price)} ({margin_guardrail.min_margin_pct:.0%} over cost) and was "
                f"raised to {money(margin_guardrail.suggested_price)}."
            )

    # The action reported must match the price actually recommended: the
    # margin floor can lift a "lower" suggestion back to (or above) the
    # current price, which used to read "Lower price to 10.45" for a
    # product currently priced 10.00.
    action = rec.action
    if final_suggested_price > own["current_price"]:
        action = "raise"
    elif final_suggested_price < own["current_price"]:
        action = "lower"
    else:
        action = "hold"
    if action != rec.action:
        explanation += f" Net recommendation: {action} (from {money(own['current_price'])} to {money(final_suggested_price)})."

    # Demand and stock decide whether following the market is wise. Found in
    # acceptance testing: a best-seller that runs out in two weeks was told
    # to cut its price (selling out sooner and giving away margin), and a
    # product growing 27% month on month was told the same.
    market_action = action
    demand = _demand_context(conn, tenant_id, product_id)
    hold_reason = None
    if action == "lower" and demand:
        if demand["stock_action"] == "restock" and demand["days_of_cover"] is not None and demand["days_of_cover"] < HORIZON_DAYS:
            hold_reason = "stock_short"
            explanation += (
                f" However, stock ({_qty(demand['stock'])}) covers only about {_qty(demand['days_of_cover'])} days of the "
                f"{_qty(demand['forecast_next_30'])} units forecast for the next 30 days; lowering the price would sell "
                f"out sooner and give away margin on units that would sell anyway. Hold the price and restock first."
            )
        elif demand["sales_change_pct"] is not None and demand["sales_change_pct"] >= DEMAND_SHIFT_PCT and demand["sold_previous_30"] >= DEMAND_MIN_UNITS:
            hold_reason = "demand_rising"
            explanation += (
                f" However, sales are up {demand['sales_change_pct']:.0f}% on the previous 30 days at the current price "
                f"({_qty(demand['sold_last_30'])} vs {_qty(demand['sold_previous_30'])} units); demand does not need a price cut."
            )
    elif action == "raise" and demand:
        if demand["sales_change_pct"] is not None and demand["sales_change_pct"] <= -DEMAND_SHIFT_PCT and demand["sold_previous_30"] >= DEMAND_MIN_UNITS:
            hold_reason = "demand_falling"
            explanation += (
                f" However, sales fell {abs(demand['sales_change_pct']):.0f}% on the previous 30 days "
                f"({_qty(demand['sold_last_30'])} vs {_qty(demand['sold_previous_30'])} units); raising the price now risks losing more volume."
            )
    if hold_reason:
        action = "hold"
        final_suggested_price = own["current_price"]

    explanation += cross_currency_note

    evidence_id = evidence.insert_evidence_record(
        conn,
        tenant_id,
        "RECOMMENDATION",
        SOURCE_MODULE,
        {"product_id": product_id, "competitor_price_entry_ids": rec.source_record_ids},
        rec.confidence_score,
        explanation,
        None,
    )
    recommended_action = (
        f"Hold price at {money(final_suggested_price)} {own_currency}" if action == "hold"
        else f"{action.capitalize()} price to {money(final_suggested_price)} {own_currency}"
    )
    outcome_id = evidence.insert_recommendation_outcome(conn, evidence_id, tenant_id, recommended_action)
    conn.commit()

    logger.info(
        f"Price recommendation written tenant={tenant_id} product={product_id} "
        f"action={action} evidence_id={evidence_id}"
    )

    return {
        "status": "OK",
        "action": action,
        "current_price": own["current_price"],
        "suggested_price": final_suggested_price,
        "guardrail_clamped": change_guardrail.clamped,
        "margin_guardrail_clamped": margin_guardrail.clamped if margin_guardrail is not None else None,
        "matched_competitor_count": rec.matched_competitor_count,
        "market_action": market_action,
        "hold_reason": hold_reason,
        "demand": demand,
        "market": {"average": rec.market_avg, "median": rec.market_median, "min": rec.market_min, "max": rec.market_max},
        "confidence_score": rec.confidence_score,
        "max_price_age_days": data_access.MAX_PRICE_AGE_DAYS,
        # The same real explanation text already persisted to this
        # evidence record (evidence.py's own explanation_text column) -
        # built above from the real recommendation/guardrail math, never
        # returned to the caller before this. Every caller had to look it
        # up separately via evidence_id even though it was already in
        # hand right here.
        "explanation": explanation,
        "evidence_id": evidence_id,
        "outcome_id": outcome_id,
    }
