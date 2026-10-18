"""
KEEL - Market Price Estimation Fallbacks.

Product policy: a product must never end up with "no market data". When no
in-region (same-currency, tracked) competitor price exists, the decision is
still made, from the best evidence available, in this order:
  MARKET_REFERENCE   same-currency market reference prices (price_lookup/:
                     a seller's public page, a public price database, a
                     shopping search) - used as found, no adjustment.
  REGIONAL_ESTIMATE  prices found OUTSIDE the tenant's region (other
                     currency, or a competitor excluded only for being out
                     of region), converted to the tenant's currency and
                     scaled by a regional adjustment factor.
  PEER_ESTIMATE      no price at all for this product: the tenant's own cost
                     x the market-to-cost multiple observed on its other
                     products (same category first).
  INTERNAL_ONLY      nothing external is available yet: decided from the
                     tenant's own cost/margin only.

The regional adjustment factor is learned from this tenant's own catalog: for
every product that has BOTH in-region and out-of-region prices, the ratio
(in-region average / converted out-of-region average); the factor is the
median of those ratios. Only when no product offers that comparison is the
configured default used (PRICING_DEFAULT_REGIONAL_FACTOR, 1.0 = prices carry
over unchanged), and the explanation says the factor is uncalibrated.

Every estimate is labelled as such in the explanation and carries a capped
confidence - an estimate is never presented as a measured local price.
"""
import os
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from src.ai.core.money import format_money, round_money
from src.ai.pricing import currency as currency_service
from src.ai.pricing import data_access

MARKET_REFERENCE = "MARKET_REFERENCE"
REGIONAL_ESTIMATE = "REGIONAL_ESTIMATE"
PEER_ESTIMATE = "PEER_ESTIMATE"
INTERNAL_ONLY = "INTERNAL_ONLY"

DEFAULT_REGIONAL_FACTOR = float(os.getenv("PRICING_DEFAULT_REGIONAL_FACTOR", "1.0"))
# A learned factor outside this band is treated as bad calibration data
# (mismatched units/packs), not a real regional price difference.
MIN_REGIONAL_FACTOR, MAX_REGIONAL_FACTOR = 0.25, 4.0
MIN_PEERS_FOR_CATEGORY_SCOPE = 2

CONFIDENCE_CAP = {MARKET_REFERENCE: 0.50, REGIONAL_ESTIMATE: 0.45, PEER_ESTIMATE: 0.30, INTERNAL_ONLY: 0.15}
UNCALIBRATED_CONFIDENCE_CAP = 0.30

# Cross-rates are not stored for every pair; USD/EUR are tried as pivots.
_PIVOT_CURRENCIES = ("USD", "EUR")


@dataclass
class Estimate:
    basis: str
    prices: List[dict] = field(default_factory=list)  # synthetic competitor records for build_recommendation
    confidence_cap: float = 0.15
    note: str = ""
    competitor_price_ids: List[str] = field(default_factory=list)
    market_observation_ids: List[str] = field(default_factory=list)


def convert_amount(conn, amount: float, from_currency: str, to_currency: str) -> Optional[float]:
    """Direct rate first, then via a pivot currency. None if no rate path exists."""
    if from_currency == to_currency:
        return amount
    result = currency_service.convert(conn, amount, from_currency, to_currency)
    if result is not None:
        return result.converted_amount
    for pivot in _PIVOT_CURRENCIES:
        if pivot in (from_currency, to_currency):
            continue
        first = currency_service.convert(conn, amount, from_currency, pivot)
        second = currency_service.convert(conn, first.converted_amount, pivot, to_currency) if first else None
        if second is not None:
            return second.converted_amount
    return None


def _clamp_factor(factor: float) -> float:
    return min(max(factor, MIN_REGIONAL_FACTOR), MAX_REGIONAL_FACTOR)


def learn_regional_factor(conn, snapshot: List[dict], own_currency: str) -> Tuple[float, int]:
    """(factor, number of products it was learned from). 0 samples = default."""
    ratios = []
    for product in snapshot:
        local = [p for p, c in product["prices"] if c == own_currency]
        foreign = [
            converted
            for p, c in product["prices"]
            if c != own_currency
            for converted in [convert_amount(conn, p, c, own_currency)]
            if converted is not None
        ]
        if local and foreign and statistics.mean(foreign) > 0:
            ratios.append(statistics.mean(local) / statistics.mean(foreign))
    if not ratios:
        return _clamp_factor(DEFAULT_REGIONAL_FACTOR), 0
    return _clamp_factor(statistics.median(ratios)), len(ratios)


def peer_market_price(
    snapshot: List[dict], product_id: str, category: Optional[str], cost: Optional[float], own_currency: str,
) -> Optional[Tuple[float, int, str]]:
    """(estimated market price, number of peers, scope) from the market/cost
    multiple of this tenant's other products; same category preferred."""
    if not cost or cost <= 0:
        return None
    peers = []
    for product in snapshot:
        if product["product_id"] == product_id or not product["cost"] or product["cost"] <= 0:
            continue
        local = [p for p, c in product["prices"] if c == own_currency]
        if local:
            peers.append((product["category"], statistics.mean(local) / product["cost"]))
    same_category = [r for cat, r in peers if category and cat == category]
    if len(same_category) >= MIN_PEERS_FOR_CATEGORY_SCOPE:
        return round_money(cost * statistics.median(same_category), own_currency), len(same_category), "same-category"
    if peers:
        return round_money(cost * statistics.median([r for _, r in peers]), own_currency), len(peers), "catalog-wide"
    return None


def build_estimate(conn, tenant_id: str, product_id: str, own: dict) -> Estimate:
    """Always returns an Estimate - the last rung is INTERNAL_ONLY."""
    own_currency = own["currency"]
    money = lambda amount: format_money(amount, own_currency)  # noqa: E731
    references = data_access.load_reference_competitor_prices(conn, tenant_id, product_id)
    snapshot = None

    if references:
        foreign_present = any(r["currency"] != own_currency for r in references)
        factor, samples = (1.0, 0)
        if foreign_present:
            snapshot = data_access.load_tenant_market_snapshot(conn, tenant_id)
            factor, samples = learn_regional_factor(conn, snapshot, own_currency)

        adjusted, unconverted, conversions = [], set(), []
        for record in references:
            amount = convert_amount(conn, record["price_found"], record["currency"], own_currency)
            if amount is None:
                unconverted.add(record["currency"])
                continue
            is_foreign = record["currency"] != own_currency
            final = round_money(amount * (factor if is_foreign else 1.0), own_currency)
            adjusted.append({**record, "price_found": final, "currency": own_currency})
            if is_foreign:
                conversions.append(f"{record['price_found']:.2f} {record['currency']} -> {money(amount)} {own_currency}")

        if adjusted:
            sources = sorted({r["source"] for r in adjusted})
            if not foreign_present:
                basis, cap = MARKET_REFERENCE, CONFIDENCE_CAP[MARKET_REFERENCE]
                note = (
                    f"No tracked in-region competitor price exists for this product, so the estimate uses "
                    f"{len(adjusted)} market reference price(s) found for it ({', '.join(sources)})."
                )
            else:
                basis = REGIONAL_ESTIMATE
                origin = ", ".join(sorted({r["currency"] for r in references if r["currency"] != own_currency}))
                calibration = (
                    f"regional factor {factor:.2f} learned from {samples} product(s) with prices in both markets"
                    if samples
                    else f"regional factor {factor:.2f} (default - no product has prices in both markets to calibrate it)"
                )
                note = (
                    f"No in-region competitor price exists for this product, so the estimate uses "
                    f"{len(adjusted)} reference price(s), including out-of-region ones ({origin}) converted to "
                    f"{own_currency} ({'; '.join(conversions)}) and adjusted for the local market: {calibration}."
                )
                cap = CONFIDENCE_CAP[REGIONAL_ESTIMATE] if samples else UNCALIBRATED_CONFIDENCE_CAP
            if unconverted:
                note += f" Prices in {', '.join(sorted(unconverted))} were skipped (no exchange-rate path)."
            return Estimate(
                basis, adjusted, cap, note,
                [r["price_entry_id"] for r in adjusted if r["source"] == "competitor"],
                [r["price_entry_id"] for r in adjusted if r["source"] == "market_reference"],
            )

    if own.get("cost"):
        snapshot = snapshot or data_access.load_tenant_market_snapshot(conn, tenant_id)
        category = next((p["category"] for p in snapshot if p["product_id"] == product_id), None)
        peer = peer_market_price(snapshot, product_id, category, own["cost"], own_currency)
        if peer is not None:
            price, peers, scope = peer
            return Estimate(
                PEER_ESTIMATE,
                [{"price_entry_id": None, "price_found": price, "currency": own_currency}],
                CONFIDENCE_CAP[PEER_ESTIMATE],
                f"No competitor price was found for this product yet, so the market price is estimated from its cost "
                f"({money(own['cost'])}) and the market-to-cost multiple of {peers} {scope} product(s) that do have "
                f"market data.",
            )

    return Estimate(
        INTERNAL_ONLY, [], CONFIDENCE_CAP[INTERNAL_ONLY],
        "No competitor price is available for this product or comparable ones yet; this decision uses the "
        "product's own cost and margin only, and market collection for it is still being widened.",
    )
