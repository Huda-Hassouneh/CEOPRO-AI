"""
Unit tests for src/ai/marketing/positioning.py - derive_positioning_label()
is a thin wrapper around dashboard/competitor_pricing.py's own real query
function, mocked here at that call site (its own correctness is covered
by test_dashboard_competitor_pricing_integration_db.py).
"""
from unittest.mock import MagicMock, patch

from src.ai.marketing import positioning


def _row(product_id, price_gap_pct):
    return {
        "product_id": product_id, "product_name": "Widget", "currency": "JOD",
        "your_price": 100.0, "market_average_price": 100.0, "price_gap_pct": price_gap_pct,
        "competitors_compared": 3,
    }


def test_returns_none_when_no_product_id():
    assert positioning.derive_positioning_label(MagicMock(), "t1", None) is None


def test_returns_none_when_product_has_no_matched_pricing_data():
    with patch("src.ai.marketing.positioning.competitor_pricing.get_competitor_price_positioning", return_value=[_row("other", 20.0)]):
        assert positioning.derive_positioning_label(MagicMock(), "t1", "p1") is None


def test_returns_premium_above_threshold():
    with patch("src.ai.marketing.positioning.competitor_pricing.get_competitor_price_positioning", return_value=[_row("p1", 25.0)]):
        assert positioning.derive_positioning_label(MagicMock(), "t1", "p1") == "PREMIUM"


def test_returns_budget_below_threshold():
    with patch("src.ai.marketing.positioning.competitor_pricing.get_competitor_price_positioning", return_value=[_row("p1", -30.0)]):
        assert positioning.derive_positioning_label(MagicMock(), "t1", "p1") == "BUDGET"


def test_returns_mid_range_within_band():
    with patch("src.ai.marketing.positioning.competitor_pricing.get_competitor_price_positioning", return_value=[_row("p1", 3.0)]):
        assert positioning.derive_positioning_label(MagicMock(), "t1", "p1") == "MID_RANGE"


def test_boundary_values_are_inclusive():
    with patch("src.ai.marketing.positioning.competitor_pricing.get_competitor_price_positioning", return_value=[_row("p1", 15.0)]):
        assert positioning.derive_positioning_label(MagicMock(), "t1", "p1") == "PREMIUM"
    with patch("src.ai.marketing.positioning.competitor_pricing.get_competitor_price_positioning", return_value=[_row("p1", -15.0)]):
        assert positioning.derive_positioning_label(MagicMock(), "t1", "p1") == "BUDGET"
