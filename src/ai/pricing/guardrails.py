"""
CEOPRO AI - Pricing Guardrails (spec S19: "Pricing must use ... Guardrails";
"The system must never automatically change prices without explicit
authorization").

Two independent guardrails: apply_price_change_guardrail() bounds how far a
suggestion can move from the current price; apply_margin_guardrail() bounds
how far it can drop below cost, using Final_schema.sql's products.cost_price.
Deliberately two separate functions rather than one combined one - a caller
with no cost data (cost_price is nullable - not every product will have it
populated) can still apply the price-change guardrail without the margin one
silently no-oping in a way that's hard to distinguish from "checked and fine".
"""

import os
from dataclasses import dataclass
from typing import Optional

MAX_PRICE_CHANGE_PCT = float(os.getenv("PRICING_MAX_CHANGE_PCT", "0.15"))
MIN_MARGIN_PCT = float(os.getenv("PRICING_MIN_MARGIN_PCT", "0.10"))


@dataclass
class GuardrailResult:
    suggested_price: float
    clamped: bool
    max_change_pct: float

    def as_dict(self) -> dict:
        return {"suggested_price": self.suggested_price, "clamped": self.clamped, "max_change_pct": self.max_change_pct}


@dataclass
class MarginGuardrailResult:
    suggested_price: float
    clamped: bool
    min_margin_pct: float
    floor_price: float

    def as_dict(self) -> dict:
        return {
            "suggested_price": self.suggested_price,
            "clamped": self.clamped,
            "min_margin_pct": self.min_margin_pct,
            "floor_price": self.floor_price,
        }


def apply_price_change_guardrail(
    current_price: float, raw_suggested_price: float, max_change_pct: float = None
) -> GuardrailResult:
    max_change_pct = MAX_PRICE_CHANGE_PCT if max_change_pct is None else max_change_pct

    lower_bound = current_price * (1 - max_change_pct)
    upper_bound = current_price * (1 + max_change_pct)

    clamped_price = min(max(raw_suggested_price, lower_bound), upper_bound)
    was_clamped = clamped_price != raw_suggested_price

    return GuardrailResult(suggested_price=round(clamped_price, 2), clamped=was_clamped, max_change_pct=max_change_pct)


def apply_margin_guardrail(
    cost: Optional[float], suggested_price: float, min_margin_pct: float = None
) -> Optional[MarginGuardrailResult]:
    """
    Raises `suggested_price` up to `cost * (1 + min_margin_pct)` when that
    floor is higher - never lowers a price, only protects against
    recommending a sale at (or dangerously close to) a loss. Returns None
    when cost is unknown (nullable products.cost_price) rather than
    pretending a floor of zero is meaningful.
    """
    if cost is None:
        return None
    min_margin_pct = MIN_MARGIN_PCT if min_margin_pct is None else min_margin_pct

    floor_price = round(cost * (1 + min_margin_pct), 2)
    clamped_price = max(suggested_price, floor_price)
    was_clamped = clamped_price != suggested_price

    return MarginGuardrailResult(
        suggested_price=clamped_price, clamped=was_clamped, min_margin_pct=min_margin_pct, floor_price=floor_price
    )
