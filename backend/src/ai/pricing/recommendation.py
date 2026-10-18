"""
KEEL - Rule-Based Price Recommendation (spec S19, S23).
Transparent, explainable weighted rule - not a learned model. Spec S19: "Learned
pricing must remain disabled until enough historical price-change data
exists" (recommendation_outcomes is currently empty, so there is no such
history yet). Pure function - no I/O - independently unit-testable.
"""

import os
import statistics
from dataclasses import dataclass, field
from typing import List, Optional

from src.ai.core.money import format_money, round_money

# How far above/below the market average our price has to be before a change
# is suggested at all - avoids nudging an already-competitive price.
COMPETITIVENESS_THRESHOLD_PCT = float(os.getenv("PRICING_COMPETITIVENESS_THRESHOLD_PCT", "0.05"))

# Minimum matched competitors before a recommendation is made with normal
# confidence, mirroring the forecasting module's cold-start policy (spec S23).
MIN_COMPETITORS_FOR_CONFIDENCE = int(os.getenv("PRICING_MIN_COMPETITORS_FOR_CONFIDENCE", "3"))


@dataclass
class PriceRecommendation:
    action: str  # "raise" | "lower" | "hold"
    current_price: float
    raw_suggested_price: float
    market_min: float
    market_max: float
    market_avg: float
    market_median: float
    matched_competitor_count: int
    confidence_score: float
    explanation: str
    source_record_ids: List[str] = field(default_factory=list)
    # LOCAL_MARKET = measured in-region competitor prices; every other value
    # is an estimate (see estimation.py) and is labelled as such everywhere.
    basis: str = "LOCAL_MARKET"

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "current_price": self.current_price,
            "raw_suggested_price": self.raw_suggested_price,
            "market_min": self.market_min,
            "market_max": self.market_max,
            "market_avg": self.market_avg,
            "market_median": self.market_median,
            "matched_competitor_count": self.matched_competitor_count,
            "confidence_score": self.confidence_score,
            "explanation": self.explanation,
            "basis": self.basis,
        }


def _confidence_for_sample_size(n: int) -> float:
    """More matched competitors -> more confidence, capped well below certainty (rule-based, not learned)."""
    if n <= 0:
        return 0.0
    return round(min(0.75, 0.25 + 0.10 * min(n, MIN_COMPETITORS_FOR_CONFIDENCE * 2)), 2)


def build_recommendation(
    current_price: float, matched_competitors: List[dict], currency: Optional[str] = None
) -> Optional[PriceRecommendation]:
    """
    `matched_competitors` must already be filtered to same-currency, ALLOWED,
    exact-data, name-matched records (see matching.py / data_access.py).
    Returns None if there's nothing to compare against (cold-start case -
    caller should record UNKNOWN evidence, not a recommendation, per S23).
    """
    if not matched_competitors:
        return None

    prices = [float(c["price_found"]) for c in matched_competitors]
    money = lambda amount: format_money(amount, currency)  # noqa: E731
    market_min, market_max = min(prices), max(prices)
    market_avg = statistics.mean(prices)
    market_median = statistics.median(prices)

    upper = market_avg * (1 + COMPETITIVENESS_THRESHOLD_PCT)
    lower = market_avg * (1 - COMPETITIVENESS_THRESHOLD_PCT)

    if current_price > upper:
        action = "lower"
        raw_suggested_price = market_avg
        explanation = (
            f"Current price {money(current_price)} is above the {len(prices)}-competitor market average "
            f"{money(market_avg)} (range {money(market_min)}-{money(market_max)}) by more than "
            f"{COMPETITIVENESS_THRESHOLD_PCT:.0%}; suggesting a move toward the market average."
        )
    elif current_price < lower:
        action = "raise"
        raw_suggested_price = market_avg
        explanation = (
            f"Current price {money(current_price)} is below the {len(prices)}-competitor market average "
            f"{money(market_avg)} (range {money(market_min)}-{money(market_max)}) by more than "
            f"{COMPETITIVENESS_THRESHOLD_PCT:.0%}; suggesting a move toward the market average."
        )
    else:
        action = "hold"
        raw_suggested_price = current_price
        explanation = (
            f"Current price {money(current_price)} is already within {COMPETITIVENESS_THRESHOLD_PCT:.0%} of the "
            f"{len(prices)}-competitor market average {money(market_avg)}; no change suggested."
        )

    return PriceRecommendation(
        action=action,
        current_price=current_price,
        raw_suggested_price=round_money(raw_suggested_price, currency),
        market_min=market_min,
        market_max=market_max,
        market_avg=round_money(market_avg, currency),
        market_median=round_money(market_median, currency),
        matched_competitor_count=len(prices),
        confidence_score=_confidence_for_sample_size(len(prices)),
        explanation=explanation,
        source_record_ids=[c["price_entry_id"] for c in matched_competitors if c.get("price_entry_id")],
    )


def build_internal_recommendation(
    current_price: float, cost: Optional[float], min_margin_pct: float, currency: Optional[str] = None
) -> PriceRecommendation:
    """
    Last-resort decision when no market evidence of any kind exists: judged on
    the tenant's own margin only. Raises a price below the minimum-margin
    floor; otherwise holds. Never "lower" - without market evidence there is
    no basis to cut a price.
    """
    money = lambda amount: format_money(amount, currency)  # noqa: E731
    floor = round_money(cost * (1 + min_margin_pct), currency) if cost else None
    if floor is not None and current_price < floor:
        action, suggested = "raise", floor
        explanation = (
            f"Current price {money(current_price)} is below the minimum-margin floor {money(floor)} "
            f"({min_margin_pct:.0%} over cost {money(cost)}); suggesting the floor."
        )
    else:
        action, suggested = "hold", current_price
        explanation = f"Current price {money(current_price)} meets the minimum margin; no change suggested."
    return PriceRecommendation(
        action=action, current_price=current_price, raw_suggested_price=round_money(suggested, currency),
        market_min=current_price, market_max=current_price, market_avg=current_price, market_median=current_price,
        matched_competitor_count=0, confidence_score=0.0, explanation=explanation, basis="INTERNAL_ONLY",
    )
