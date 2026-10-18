"""
Offline, pure-logic tests for insights/cross_signal.py - no DB, no I/O,
mirrors pricing/tests/test_pricing_recommendation.py's own style for the
same reason: this is a rule-based, explainable engine (spec S19's
rationale for pricing applies here too - no outcome history exists yet
to train a learned model on which cross-signal patterns are actually
useful), so its branches are exhaustively testable as pure functions.
"""

from src.ai.insights.cross_signal import ProductSignals, detect_insights, detect_insights_for_product


def _signals(**overrides):
    defaults = {
        "product_id": "p1",
        "product_name": "Widget",
        "price_gap_pct": None,
        "sentiment_score": None,
        "sales_trend_pct": None,
        "forecast_trend_pct": None,
    }
    defaults.update(overrides)
    return ProductSignals(**defaults)


def test_returns_nothing_when_no_signals_are_available():
    assert detect_insights_for_product(_signals()) == []


def test_returns_nothing_from_a_single_raw_signal_alone():
    """A cross-signal insight requires at least two independent signals
    to agree - one raw fact alone (price is high, sentiment is bad, sales
    are falling) is not yet a correlation. forecast_trend_pct is the one
    exception: it is itself already a derived cross-check (the forecast
    model's output compared against the product's own recent sales pace -
    see insights/pipeline.py::_forecast_trend_pct()), not a single raw
    fact, so it can stand alone - covered separately below."""
    assert detect_insights_for_product(_signals(price_gap_pct=20.0)) == []
    assert detect_insights_for_product(_signals(sentiment_score=-0.5)) == []
    assert detect_insights_for_product(_signals(sales_trend_pct=-30.0)) == []


def test_falling_forecast_alone_is_a_valid_insight_since_it_is_already_a_cross_check():
    insights = detect_insights_for_product(_signals(forecast_trend_pct=-30.0))
    assert len(insights) == 1
    assert insights[0].category == "demand"


def test_overpriced_and_falling_sales_and_falling_forecast_is_the_strongest_insight():
    signals = _signals(price_gap_pct=20.0, sales_trend_pct=-25.0, forecast_trend_pct=-20.0)
    insights = detect_insights_for_product(signals)
    assert len(insights) == 1
    assert insights[0].category == "pricing"
    assert "Widget" in insights[0].message
    assert insights[0].confidence == 0.9


def test_overpriced_and_falling_sales_without_forecast_data():
    signals = _signals(price_gap_pct=20.0, sales_trend_pct=-25.0)
    insights = detect_insights_for_product(signals)
    assert len(insights) == 1
    assert insights[0].category == "pricing"
    assert insights[0].confidence == 0.7


def test_overpriced_and_negative_sentiment():
    signals = _signals(price_gap_pct=20.0, sentiment_score=-0.5)
    insights = detect_insights_for_product(signals)
    assert len(insights) == 1
    assert "feedback" in insights[0].message.lower()


def test_negative_sentiment_and_falling_sales_flags_a_quality_issue_not_pricing():
    signals = _signals(sentiment_score=-0.5, sales_trend_pct=-25.0)
    insights = detect_insights_for_product(signals)
    assert len(insights) == 1
    assert insights[0].category == "sentiment"
    assert "service or quality" in insights[0].message


def test_underpriced_with_rising_sales_and_non_negative_sentiment_suggests_a_price_increase():
    signals = _signals(price_gap_pct=-20.0, sales_trend_pct=25.0, sentiment_score=0.1)
    insights = detect_insights_for_product(signals)
    assert len(insights) == 1
    assert insights[0].category == "pricing"
    assert "increase" in insights[0].message.lower()


def test_underpriced_with_rising_sales_but_negative_sentiment_does_not_suggest_a_price_increase():
    """Negative sentiment should block the underpricing-opportunity read -
    a price increase would be the wrong advice while customers are
    already unhappy."""
    signals = _signals(price_gap_pct=-20.0, sales_trend_pct=25.0, sentiment_score=-0.5)
    insights = detect_insights_for_product(signals)
    assert insights == []


def test_underpriced_with_rising_forecast_also_suggests_a_price_increase():
    signals = _signals(price_gap_pct=-20.0, forecast_trend_pct=25.0)
    insights = detect_insights_for_product(signals)
    assert len(insights) == 1
    assert insights[0].category == "pricing"


def test_rising_forecast_with_competitive_price_suggests_stocking_up():
    signals = _signals(forecast_trend_pct=25.0, price_gap_pct=0.0, sales_trend_pct=None)
    insights = detect_insights_for_product(signals)
    assert len(insights) == 1
    assert insights[0].category == "demand"
    assert "stock" in insights[0].message.lower()


def test_rising_forecast_does_not_suggest_stocking_up_when_already_overpriced():
    signals = _signals(forecast_trend_pct=25.0, price_gap_pct=20.0)
    insights = detect_insights_for_product(signals)
    # overpriced + no falling-sales/sentiment signal doesn't match any
    # higher-priority rule either, so nothing fires - never a stocking-up
    # suggestion while the product is already priced above the market.
    assert insights == []


def test_falling_forecast_alone_with_no_other_bad_signal_still_surfaces_a_mild_heads_up():
    signals = _signals(forecast_trend_pct=-25.0, sales_trend_pct=5.0, sentiment_score=0.2)
    insights = detect_insights_for_product(signals)
    assert len(insights) == 1
    assert insights[0].category == "demand"
    assert insights[0].confidence == 0.4


def test_falling_forecast_is_suppressed_when_sales_are_already_falling():
    """Avoids a redundant/weaker message when the stronger sales-trend-based
    rule already applies to the same underlying situation."""
    signals = _signals(forecast_trend_pct=-25.0, sales_trend_pct=-25.0)
    insights = detect_insights_for_product(signals)
    # sales falling + forecast falling but no price/sentiment signal:
    # none of the higher-priority multi-signal rules match (they all also
    # require a price or sentiment signal), and the falling-forecast-alone
    # rule explicitly requires sales NOT falling - so nothing fires here,
    # which is correct: two agreeing-but-incomplete signals without a
    # pricing or sentiment angle isn't yet an actionable recommendation.
    assert insights == []


def test_thresholds_are_not_crossed_by_small_moves():
    signals = _signals(price_gap_pct=3.0, sales_trend_pct=-5.0, forecast_trend_pct=2.0, sentiment_score=0.05)
    assert detect_insights_for_product(signals) == []


def test_detect_insights_caps_to_max_insights_ordered_by_confidence():
    all_signals = [
        _signals(product_id="p1", product_name="A", price_gap_pct=20.0, sales_trend_pct=-25.0, forecast_trend_pct=-20.0),  # 0.9
        _signals(product_id="p2", product_name="B", sentiment_score=-0.5, sales_trend_pct=-25.0),  # 0.8
        _signals(product_id="p3", product_name="C", price_gap_pct=20.0, sales_trend_pct=-25.0),  # 0.7
        _signals(product_id="p4", product_name="D", price_gap_pct=20.0, sentiment_score=-0.5),  # 0.7
        _signals(product_id="p5", product_name="E", price_gap_pct=-20.0, sales_trend_pct=25.0),  # 0.6
        _signals(product_id="p6", product_name="F", forecast_trend_pct=25.0, price_gap_pct=0.0),  # 0.5
    ]

    top_insights = detect_insights(all_signals, max_insights=3)

    assert len(top_insights) == 3
    assert [insight.product_id for insight in top_insights] == ["p1", "p2", "p3"]


def test_detect_insights_returns_empty_list_for_no_products():
    assert detect_insights([], max_insights=5) == []
