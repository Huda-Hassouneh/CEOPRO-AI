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
from datetime import datetime, timezone

from src.ai.core.money import format_money
from src.ai.pricing import currency, data_access, estimation, evidence, guardrails, recommendation

logger = logging.getLogger("CEOPRO_AI_PRICING_PIPELINE")

SOURCE_MODULE = "ai.pricing"

# Price data older than this is still used, but the explanation says so.
OLD_DATA_NOTE_AFTER_DAYS = 90


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

    own_currency = own["currency"]
    money = lambda amount: format_money(amount, own_currency)  # noqa: E731
    estimate = None
    if competitor_prices:
        rec = recommendation.build_recommendation(own["current_price"], competitor_prices, own_currency)
    else:
        # Never "no data": widen to market reference / out-of-region prices,
        # then peer products, then internal margin (see estimation.py).
        estimate = estimation.build_estimate(conn, tenant_id, product_id, own)
        if estimate.prices:
            rec = recommendation.build_recommendation(own["current_price"], estimate.prices, own_currency)
            rec.confidence_score = min(rec.confidence_score, estimate.confidence_cap)
            rec.matched_competitor_count = (
                len(estimate.competitor_price_ids) + len(estimate.market_observation_ids) + len(estimate.comparison_ids)
            )
        else:
            rec = recommendation.build_internal_recommendation(
                own["current_price"], own["cost"], guardrails.MIN_MARGIN_PCT, own_currency
            )
            rec.confidence_score = estimate.confidence_cap
        rec.source_record_ids = estimate.competitor_price_ids
        rec.basis = estimate.basis
        rec.explanation = f"[{estimate.basis}] {estimate.note} {rec.explanation}"
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

    evidence_prices = competitor_prices or (estimate.prices if estimate else [])
    observed = [c["captured_at"] for c in evidence_prices if c.get("captured_at") is not None]
    newest_observation = max(observed) if observed else None
    age_days = (datetime.now(timezone.utc) - newest_observation).days if newest_observation else None
    if age_days is not None and age_days > OLD_DATA_NOTE_AFTER_DAYS:
        explanation += (
            f" Note: the most recent price used was collected on {newest_observation.date().isoformat()} "
            f"({age_days} days ago); treat this as a reference, not a live market price."
        )

    if estimate is None or estimate.basis != estimation.REGIONAL_ESTIMATE:
        # A regional estimate already uses (and explains) the converted prices.
        explanation += cross_currency_note

    evidence_id = evidence.insert_evidence_record(
        conn,
        tenant_id,
        "RECOMMENDATION",
        SOURCE_MODULE,
        {
            "product_id": product_id,
            "competitor_price_entry_ids": rec.source_record_ids,
            "market_observation_ids": estimate.market_observation_ids if estimate else [],
            "price_comparison_ids": estimate.comparison_ids if estimate else [],
            "data_basis": rec.basis,
        },
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
        "data_basis": rec.basis,
        "matched_competitor_count": rec.matched_competitor_count,
        "market_action": market_action,
        "hold_reason": hold_reason,
        "demand": demand,
        "market": (
            None if rec.basis == estimation.INTERNAL_ONLY
            else {"average": rec.market_avg, "median": rec.market_median, "min": rec.market_min, "max": rec.market_max}
        ),
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


def run_price_recommendations_for_all(conn, tenant_id: str) -> dict:
    """
    One decision (raise / lower / hold) for every active product - no product
    is skipped for lacking market data (see estimation.py). A failure on one
    product is recorded and the batch continues.
    """
    with conn.cursor() as cursor:
        cursor.execute("SELECT product_id FROM products WHERE tenant_id = %s AND deleted_at IS NULL;", (tenant_id,))
        product_ids = [str(row[0]) for row in cursor.fetchall()]

    results, failed = [], []
    for product_id in product_ids:
        try:
            results.append({"product_id": product_id, **run_price_recommendation(conn, tenant_id, product_id)})
        except Exception as exc:  # noqa: BLE001 - one bad product must not stop the batch
            conn.rollback()
            logger.exception(f"Price recommendation failed tenant={tenant_id} product={product_id}")
            failed.append({"product_id": product_id, "error": str(exc)})

    by_basis = {}
    for result in results:
        by_basis[result["data_basis"]] = by_basis.get(result["data_basis"], 0) + 1
    return {"total": len(product_ids), "decided": len(results), "by_data_basis": by_basis, "failed": failed, "results": results}
