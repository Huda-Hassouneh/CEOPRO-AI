"""
KEEL - Marketing Campaign Market Positioning (presentation layer, not
a new model, no new tables).

Reuses dashboard/competitor_pricing.py::get_competitor_price_positioning()
- the same real, matched-competitor price-gap-percent data the Competitor
Price Positioning dashboard card already computes - to derive a plain
budget/mid-range/premium label. This platform has no dedicated "budget vs
premium" classifier anywhere; this is the honest reuse of what it does
have (a real price gap vs the matched competitor average), not a new
signal invented for this feature.

Only meaningful for a PRODUCT-sourced campaign (a real product_id with at
least one matched competitor price). A TEXT- or URL-sourced campaign has
no product_id to look up and therefore no real pricing signal to derive a
label from - derive_positioning_label() returns None in that case rather
than guessing, matching this feature's "never fabricate" requirement.
"""
from typing import Optional

from src.ai.dashboard import competitor_pricing

# Matches this module's own price_gap_pct convention (positive = priced
# above the matched-competitor average). +/-15% is a deliberately wide
# band so a product priced close to the market average lands in
# MID_RANGE rather than flipping labels on small day-to-day price noise.
_PREMIUM_THRESHOLD_PCT = 15.0
_BUDGET_THRESHOLD_PCT = -15.0

# get_competitor_price_positioning() already caps to its own `limit` and
# sorts by |price_gap_pct| descending - this needs to scan the tenant's
# whole matched-product set to find one specific product_id, not just the
# biggest gaps, so it asks for a generous ceiling rather than that
# function's own small dashboard-card default.
_LOOKUP_LIMIT = 500


def derive_positioning_label(conn, tenant_id: str, product_id: Optional[str]) -> Optional[str]:
    """
    Returns "BUDGET" / "MID_RANGE" / "PREMIUM", or None when there is no
    real pricing signal to derive one from (no product_id, or that
    product has no matched competitor prices yet - the same condition
    get_competitor_price_positioning() itself silently excludes a product
    for, via its own `avg_competitor_price <= 0: continue` guard).
    """
    if not product_id:
        return None

    positioning = competitor_pricing.get_competitor_price_positioning(conn, tenant_id, limit=_LOOKUP_LIMIT)
    row = next((r for r in positioning if r["product_id"] == product_id), None)
    if row is None:
        return None

    gap = row["price_gap_pct"]
    if gap >= _PREMIUM_THRESHOLD_PCT:
        return "PREMIUM"
    if gap <= _BUDGET_THRESHOLD_PCT:
        return "BUDGET"
    return "MID_RANGE"
