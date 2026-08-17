"""
CEOPRO AI - Pricing Guardrails (spec S19: "Pricing must use ... Guardrails";
"The system must never automatically change prices without explicit
authorization").

Two independent guardrails: apply_price_change_guardrail() bounds how far a
suggestion can move from the current price; apply_margin_guardrail() bounds
how far it can drop below cost, now that `products.cost` exists
(PENDING_ACTIONS.md #14, resolved). Deliberately two separate functions
rather than one combined one - a caller with no cost data (still the
common case - cost is nullable and most products won't have it populated)
can apply just the price-change guardrail without the margin one silently
no-op-ing inside a combined function, which would be easy to miss.
"""

import os
from dataclasses import dataclass
from typing import Optional

MAX_PRICE_CHANGE_PCT = float(os.getenv("PRICING_MAX_CHANGE_PCT", "0.15"))
# Not spec-derived (spec S19 requires margin guardrails without naming an
# exact floor) - a practical minimum-acceptable-margin default, same
# "documented, overridable, not pulled from the spec" shape as every other
# undomains-specified threshold in this track (e.g. forecasting's
# MIN_HISTORY_DAYS).
MIN_MARGIN_PCT = float(os.getenv("PRICING_MIN_MARGIN_PCT", "0.10"))


@dataclass
class GuardrailResult:
    suggested_price: float
    clamped: bool
    max_change_pct: float

    def as_dict(self) -> dict:
        return {"suggested_price": self.suggested_price, "clamped": self.clamped, "max_change_pct": self.max_change_pct}


def apply_price_change_guardrail(
    current_price: float, raw_suggested_price: float, max_change_pct: float = None
) -> GuardrailResult:
    max_change_pct = MAX_PRICE_CHANGE_PCT if max_change_pct is None else max_change_pct

    lower_bound = current_price * (1 - max_change_pct)
    upper_bound = current_price * (1 + max_change_pct)

    clamped_price = min(max(raw_suggested_price, lower_bound), upper_bound)
    was_clamped = clamped_price != raw_suggested_price

    return GuardrailResult(suggested_price=round(clamped_price, 2), clamped=was_clamped, max_change_pct=max_change_pct)


@dataclass
class MarginGuardrailResult:
    suggested_price: float
    clamped: bool
    min_margin_pct: float
    price_floor: float

    def as_dict(self) -> dict:
        return {
            "suggested_price": self.suggested_price,
            "clamped": self.clamped,
            "min_margin_pct": self.min_margin_pct,
            "price_floor": self.price_floor,
        }


def apply_margin_guardrail(
    cost: Optional[float], suggested_price: float, min_margin_pct: float = None
) -> Optional[MarginGuardrailResult]:
    """
    Raises suggested_price up to cost * (1 + min_margin_pct) if it would
    otherwise fall below that floor - deliberately a floor-raise only, never
    lowers a price the price-change guardrail already approved. Returns None
    (not a guess) when cost is unknown, so a caller can't accidentally treat
    "no cost data" as "margin is fine."
    """
    if cost is None:
        return None

    min_margin_pct = MIN_MARGIN_PCT if min_margin_pct is None else min_margin_pct
    price_floor = round(cost * (1 + min_margin_pct), 2)

    if suggested_price >= price_floor:
        return MarginGuardrailResult(
            suggested_price=suggested_price, clamped=False, min_margin_pct=min_margin_pct, price_floor=price_floor
        )

    return MarginGuardrailResult(
        suggested_price=price_floor, clamped=True, min_margin_pct=min_margin_pct, price_floor=price_floor
    )
