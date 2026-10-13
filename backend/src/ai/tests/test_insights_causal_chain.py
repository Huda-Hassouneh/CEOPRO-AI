"""
Offline, pure-logic tests for insights/causal_chain.py - no DB, no I/O.
Mirrors test_insights_cross_signal.py's own style/rigor for the same
reason: this is a second, independent rule-based detector and deserves
the same exhaustive branch coverage.
"""
from datetime import date, timedelta

from src.ai.insights.causal_chain import (
    PriceDropEvent, detect_causal_price_sales_insight, detect_price_drop_events,
)


def _daily_sales(start: date, days: int, units_per_day: float) -> dict:
    return {start + timedelta(days=i): units_per_day for i in range(days)}


def test_detect_price_drop_events_finds_a_real_drop():
    history = [(date(2026, 1, 1), 100.0), (date(2026, 1, 15), 80.0)]
    events = detect_price_drop_events(history)
    assert len(events) == 1
    assert events[0].event_date == date(2026, 1, 15)
    assert events[0].drop_pct == 20.0


def test_detect_price_drop_events_ignores_small_moves():
    history = [(date(2026, 1, 1), 100.0), (date(2026, 1, 15), 95.0)]  # 5% - below the 10% threshold
    assert detect_price_drop_events(history) == []


def test_detect_price_drop_events_ignores_price_increases():
    history = [(date(2026, 1, 1), 80.0), (date(2026, 1, 15), 100.0)]
    assert detect_price_drop_events(history) == []


def test_detect_price_drop_events_finds_multiple_events_in_one_history():
    history = [
        (date(2026, 1, 1), 100.0),
        (date(2026, 1, 15), 80.0),   # -20%
        (date(2026, 2, 1), 82.0),    # +2.5%, not an event
        (date(2026, 2, 15), 60.0),   # -26.8%
    ]
    events = detect_price_drop_events(history)
    assert len(events) == 2
    assert events[0].event_date == date(2026, 1, 15)
    assert events[1].event_date == date(2026, 2, 15)


def test_detect_price_drop_events_returns_empty_for_a_single_observation():
    assert detect_price_drop_events([(date(2026, 1, 1), 100.0)]) == []


def test_causal_insight_none_when_no_price_events():
    daily_sales = _daily_sales(date(2026, 1, 1), 60, 10.0)
    result = detect_causal_price_sales_insight("p1", "Widget", "Rival Co", [], daily_sales)
    assert result is None


def test_causal_insight_none_when_sales_do_not_decline_after_the_event():
    event = PriceDropEvent(event_date=date(2026, 2, 1), price_before=100.0, price_after=80.0, drop_pct=20.0)
    daily_sales = _daily_sales(date(2026, 1, 1), 60, 10.0)  # flat throughout - no decline at all
    result = detect_causal_price_sales_insight("p1", "Widget", "Rival Co", [event], daily_sales)
    assert result is None


def test_causal_insight_none_when_there_is_no_sales_data_before_the_event():
    event = PriceDropEvent(event_date=date(2026, 2, 1), price_before=100.0, price_after=80.0, drop_pct=20.0)
    daily_sales = _daily_sales(date(2026, 2, 1), 30, 5.0)  # only sales AFTER the event exist
    result = detect_causal_price_sales_insight("p1", "Widget", "Rival Co", [event], daily_sales)
    assert result is None


def test_causal_insight_possible_tier_for_a_moderate_decline():
    event = PriceDropEvent(event_date=date(2026, 2, 1), price_before=100.0, price_after=88.0, drop_pct=12.0)
    daily_sales = {}
    daily_sales.update(_daily_sales(date(2026, 1, 18), 14, 10.0))  # before: 10/day
    daily_sales.update(_daily_sales(date(2026, 2, 1), 14, 8.0))    # after: 8/day = -20%
    result = detect_causal_price_sales_insight("p1", "Widget", "Rival Co", [event], daily_sales)
    assert result is not None
    assert result.category == "causal_timing"
    assert result.confidence == 0.55
    assert "not certain yet" in result.message
    assert "Widget" in result.message and "Rival Co" in result.message


def test_causal_insight_strong_tier_for_a_large_drop_and_large_decline():
    event = PriceDropEvent(event_date=date(2026, 2, 1), price_before=100.0, price_after=70.0, drop_pct=30.0)
    daily_sales = {}
    daily_sales.update(_daily_sales(date(2026, 1, 18), 14, 10.0))  # before: 10/day
    daily_sales.update(_daily_sales(date(2026, 2, 1), 14, 5.0))    # after: 5/day = -50%
    result = detect_causal_price_sales_insight("p1", "Widget", "Rival Co", [event], daily_sales)
    assert result is not None
    assert result.confidence == 0.85
    assert "strong pattern" in result.message


def test_causal_insight_picks_the_strongest_of_multiple_events():
    weak_event = PriceDropEvent(event_date=date(2026, 1, 5), price_before=100.0, price_after=85.0, drop_pct=15.0)
    strong_event = PriceDropEvent(event_date=date(2026, 3, 1), price_before=100.0, price_after=70.0, drop_pct=30.0)
    daily_sales = {}
    daily_sales.update(_daily_sales(date(2025, 12, 22), 14, 10.0))
    daily_sales.update(_daily_sales(date(2026, 1, 5), 40, 9.0))    # mild decline after weak_event
    daily_sales.update(_daily_sales(date(2026, 2, 15), 14, 10.0))  # back up before strong_event
    daily_sales.update(_daily_sales(date(2026, 3, 1), 14, 4.0))    # sharp decline after strong_event

    result = detect_causal_price_sales_insight("p1", "Widget", "Rival Co", [weak_event, strong_event], daily_sales)
    assert result is not None
    assert date(2026, 3, 1).isoformat() in result.message
    assert result.confidence == 0.85


def test_causal_insight_never_claims_certainty_language():
    """The vision explicitly requires never presenting correlation as
    definite causation - even the STRONG tier must stay hedged."""
    event = PriceDropEvent(event_date=date(2026, 2, 1), price_before=100.0, price_after=70.0, drop_pct=30.0)
    daily_sales = {}
    daily_sales.update(_daily_sales(date(2026, 1, 18), 14, 10.0))
    daily_sales.update(_daily_sales(date(2026, 2, 1), 14, 5.0))
    result = detect_causal_price_sales_insight("p1", "Widget", "Rival Co", [event], daily_sales)
    message_lower = result.message.lower()
    for forbidden in ("because of", "caused by", "definitely", "certainly"):
        assert forbidden not in message_lower
