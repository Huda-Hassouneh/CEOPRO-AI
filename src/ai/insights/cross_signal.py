"""
CEOPRO AI - Cross-Signal Strategic Insight Detection.

Pure, I/O-free rule logic (mirrors pricing/recommendation.py's own
"transparent, explainable weighted rule, not a learned model" approach -
spec S19's rationale for pricing applies equally here: there isn't yet
enough historical outcome data anywhere in this platform to train a
model on which cross-signal patterns actually predict a good business
outcome, so a rule-based system that a human can read and verify is the
right, honest choice for now, not a stopgap).

The real gap this closes: every existing subsystem (pricing, sentiment,
sales, forecasting) already computes its own signal correctly, but
nothing ever correlates them - a chatbot asked "how am I doing" could
only ever repeat one fact at a time, never connect "your price is above
the market AND sales are falling AND next period's demand is forecast to
keep falling" into the single, more useful insight a human advisor would
actually give. detect_insights_for_product() below is that correlation step: every rule
requires at least two independent real signals to agree before it fires -
a single RAW signal alone (e.g. "price is high") is never enough, it's
just one fact restated, not a cross-signal insight. The one deliberate
exception is forecast_trend_pct itself: it is already a derived
cross-check, not a single raw fact - insights/pipeline.py computes it by
comparing the forecasting model's own output against that product's
recent actual sales pace, so a real forecast/sales-history mismatch can
stand alone as its own (lower-confidence) insight before ever being
combined with pricing or sentiment.

Every message is already plain, jargon-free business language - see
llm_client.py's SYSTEM_PROMPT for why that discipline has to be enforced
at the source, not left to the LLM to translate on every call.
"""

import os
from dataclasses import dataclass
from typing import List, Optional

# How far above/below the market average a price has to be before it's
# treated as a real signal, not noise - mirrors pricing/recommendation.py's
# own COMPETITIVENESS_THRESHOLD_PCT (kept as a separate constant since
# this module's purpose - flagging a cross-signal pattern - can reasonably
# use a different threshold than pricing's own direct recommendation).
PRICE_GAP_THRESHOLD_PCT = float(os.getenv("INSIGHTS_PRICE_GAP_THRESHOLD_PCT", "10.0"))

# How much recent sales (or a forecast) has to move, period over period,
# before it's a real trend rather than ordinary week-to-week noise.
SALES_TREND_THRESHOLD_PCT = float(os.getenv("INSIGHTS_SALES_TREND_THRESHOLD_PCT", "15.0"))
FORECAST_TREND_THRESHOLD_PCT = float(os.getenv("INSIGHTS_FORECAST_TREND_THRESHOLD_PCT", "15.0"))

# Sentiment scores here are on the same -1..1 scale sentiment/data_access.py
# already produces (avg positive_probability - avg negative_probability).
SENTIMENT_THRESHOLD = float(os.getenv("INSIGHTS_SENTIMENT_THRESHOLD", "0.15"))


@dataclass
class ProductSignals:
    """
    One product's current reading across every independent signal this
    platform tracks. Any field left None means that signal genuinely
    isn't available yet (no competitor price observation, no analyzed
    reviews, no sales history, no forecast) - never a fabricated zero;
    detect_insights_for_product() below treats None as "this signal
    can't be used", not as "this signal is neutral/zero".
    """

    product_id: str
    product_name: str
    price_gap_pct: Optional[float] = None  # positive = priced above the market average
    sentiment_score: Optional[float] = None  # -1..1, positive = favorable
    sales_trend_pct: Optional[float] = None  # recent 30d vs. prior 30d units, positive = rising
    forecast_trend_pct: Optional[float] = None  # forecast vs. current sales pace, positive = rising


@dataclass
class Insight:
    message: str
    category: str  # "pricing" | "sentiment" | "demand"
    product_id: str
    confidence: float  # 0..1, internal ranking only - never shown to the user


def _is_overpriced(signals: ProductSignals) -> bool:
    return signals.price_gap_pct is not None and signals.price_gap_pct >= PRICE_GAP_THRESHOLD_PCT


def _is_underpriced(signals: ProductSignals) -> bool:
    return signals.price_gap_pct is not None and signals.price_gap_pct <= -PRICE_GAP_THRESHOLD_PCT


def _is_sales_falling(signals: ProductSignals) -> bool:
    return signals.sales_trend_pct is not None and signals.sales_trend_pct <= -SALES_TREND_THRESHOLD_PCT


def _is_sales_rising(signals: ProductSignals) -> bool:
    return signals.sales_trend_pct is not None and signals.sales_trend_pct >= SALES_TREND_THRESHOLD_PCT


def _is_forecast_falling(signals: ProductSignals) -> bool:
    return signals.forecast_trend_pct is not None and signals.forecast_trend_pct <= -FORECAST_TREND_THRESHOLD_PCT


def _is_forecast_rising(signals: ProductSignals) -> bool:
    return signals.forecast_trend_pct is not None and signals.forecast_trend_pct >= FORECAST_TREND_THRESHOLD_PCT


def _is_sentiment_negative(signals: ProductSignals) -> bool:
    return signals.sentiment_score is not None and signals.sentiment_score <= -SENTIMENT_THRESHOLD


def _is_sentiment_not_negative(signals: ProductSignals) -> bool:
    """Distinct from "positive" - a product with unknown or neutral sentiment
    should not block an underpricing insight the way a genuinely negative
    signal should, but the rule should also never claim sentiment supports
    a recommendation when it's simply absent."""
    return signals.sentiment_score is None or signals.sentiment_score > -SENTIMENT_THRESHOLD


def detect_insights_for_product(signals: ProductSignals) -> List[Insight]:
    """
    Returns at most one insight per product - the single, strongest
    cross-signal pattern found, in priority order below, rather than
    multiple overlapping (or even contradictory) messages about the same
    product. Returns [] when fewer than two independent signals are
    available, or when the available signals don't cross a threshold
    together - "nothing notable" is a real, honest possible outcome, not
    a bug.
    """
    name = signals.product_name

    if _is_overpriced(signals) and _is_sales_falling(signals) and _is_forecast_falling(signals):
        return [Insight(
            message=(
                f"Your price for {name} is above the market, and both recent sales and next period's "
                f"expected demand are trending down. This is worth acting on - consider lowering the "
                f"price a little or clearly showing customers what makes it worth the extra cost, before "
                f"you lose more sales to cheaper options."
            ),
            category="pricing", product_id=signals.product_id, confidence=0.9,
        )]

    if _is_overpriced(signals) and _is_sales_falling(signals):
        return [Insight(
            message=(
                f"Your price for {name} is above the market average, and sales have slowed down recently. "
                f"The price gap may be pushing customers toward cheaper options - worth comparing your "
                f"price against competitors again."
            ),
            category="pricing", product_id=signals.product_id, confidence=0.7,
        )]

    if _is_overpriced(signals) and _is_sentiment_negative(signals):
        return [Insight(
            message=(
                f"{name} is priced above the market, and recent customer feedback has leaned negative. "
                f"Customers who aren't happy with the experience are less likely to accept paying more - "
                f"it may be worth addressing the feedback before changing the price."
            ),
            category="pricing", product_id=signals.product_id, confidence=0.7,
        )]

    if _is_sentiment_negative(signals) and _is_sales_falling(signals):
        return [Insight(
            message=(
                f"Customer sentiment has turned negative around the same time sales for {name} have "
                f"dropped. This looks more like a service or quality concern than a pricing one - it's "
                f"worth looking into recent complaints before touching the price."
            ),
            category="sentiment", product_id=signals.product_id, confidence=0.8,
        )]

    if _is_underpriced(signals) and (_is_sales_rising(signals) or _is_forecast_rising(signals)) and _is_sentiment_not_negative(signals):
        return [Insight(
            message=(
                f"You're pricing {name} well below the market, and demand is healthy. A small price "
                f"increase is unlikely to hurt sales and could add extra profit."
            ),
            category="pricing", product_id=signals.product_id, confidence=0.6,
        )]

    if _is_forecast_rising(signals) and not _is_overpriced(signals):
        return [Insight(
            message=(
                f"Demand for {name} is expected to grow in the coming period, and your price is already "
                f"competitive. This could be a good time to make sure you have enough stock ready."
            ),
            category="demand", product_id=signals.product_id, confidence=0.5,
        )]

    if _is_forecast_falling(signals) and not _is_sales_falling(signals) and not _is_sentiment_negative(signals):
        return [Insight(
            message=(
                f"Demand for {name} is expected to cool off in the coming period, even though nothing "
                f"else looks off yet. Worth planning your stock and any promotions with that in mind."
            ),
            category="demand", product_id=signals.product_id, confidence=0.4,
        )]

    return []


def detect_insights(all_signals: List[ProductSignals], max_insights: int = 5) -> List[Insight]:
    """
    Runs detect_insights_for_product() across every product, then keeps
    only the top `max_insights` by confidence - a merchant with dozens of
    products should see the handful of patterns that matter most, not an
    overwhelming list. Ties broken by product order (stable sort), never
    randomly, so the same inputs always produce the same output.
    """
    insights = []
    for signals in all_signals:
        insights.extend(detect_insights_for_product(signals))
    insights.sort(key=lambda insight: insight.confidence, reverse=True)
    return insights[:max_insights]
