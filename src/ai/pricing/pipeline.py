"""
CEOPRO AI - Price Recommendation Pipeline (spec S9, S19, S20, S22, S23, S24).
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
            f"{record['price_found']:.2f} {record['currency']} -> {result.converted_amount:.2f} {own_currency} "
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


def run_price_recommendation(conn, tenant_id: str, product_id: str) -> dict:
    own = data_access.load_own_product(conn, tenant_id, product_id)
    if own is None:
        raise ValueError(f"No product found for tenant={tenant_id} product_id={product_id}")

    competitor_prices = data_access.load_competitor_prices(conn, tenant_id, product_id, own["currency"])
    cross_currency_note = _build_cross_currency_reference(conn, tenant_id, product_id, own["currency"])

    if not competitor_prices:
        explanation = (
            f"No competitor price data found for '{own['product_name']}' in {own['currency']} "
            f"within the freshness/allow-list filters."
        ) + cross_currency_note
        evidence_id = evidence.insert_evidence_record(
            conn, tenant_id, "UNKNOWN", SOURCE_MODULE, {"product_id": product_id}, None, explanation, None
        )
        conn.commit()
        logger.info(f"No competitor prices for tenant={tenant_id} product={product_id}; evidence={evidence_id}")
        return {"status": "UNKNOWN", "evidence_id": evidence_id}

    rec = recommendation.build_recommendation(own["current_price"], competitor_prices)
    change_guardrail = guardrails.apply_price_change_guardrail(own["current_price"], rec.raw_suggested_price)
    final_suggested_price = change_guardrail.suggested_price

    explanation = rec.explanation
    if change_guardrail.clamped:
        explanation += (
            f" Suggested price {rec.raw_suggested_price:.2f} was outside the "
            f"{change_guardrail.max_change_pct:.0%} price-change guardrail and was capped to "
            f"{change_guardrail.suggested_price:.2f}."
        )

    margin_guardrail = guardrails.apply_margin_guardrail(own["cost"], final_suggested_price)
    if margin_guardrail is not None:
        final_suggested_price = margin_guardrail.suggested_price
        if margin_guardrail.clamped:
            explanation += (
                f" Suggested price {change_guardrail.suggested_price:.2f} was below the minimum-margin floor "
                f"{margin_guardrail.floor_price:.2f} ({margin_guardrail.min_margin_pct:.0%} over cost) and was "
                f"raised to {margin_guardrail.suggested_price:.2f}."
            )

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
    recommended_action = f"{rec.action.capitalize()} price to {final_suggested_price:.2f} {own['currency']}"
    outcome_id = evidence.insert_recommendation_outcome(conn, evidence_id, tenant_id, recommended_action)
    conn.commit()

    logger.info(
        f"Price recommendation written tenant={tenant_id} product={product_id} "
        f"action={rec.action} evidence_id={evidence_id}"
    )

    return {
        "status": "OK",
        "action": rec.action,
        "current_price": own["current_price"],
        "suggested_price": final_suggested_price,
        "guardrail_clamped": change_guardrail.clamped,
        "margin_guardrail_clamped": margin_guardrail.clamped if margin_guardrail is not None else None,
        "matched_competitor_count": rec.matched_competitor_count,
        "confidence_score": rec.confidence_score,
        "evidence_id": evidence_id,
        "outcome_id": outcome_id,
    }
