"""
Unit tests for src/ai/marketing/creative_direction.py::recommend_theme() -
a deterministic rule over positioning_label/category/market_overview, so
these test each branch directly rather than through the router.
market_overview.get_market_overview() is mocked at its call site (its own
correctness is covered by its own dashboard tests).
"""
from unittest.mock import MagicMock, patch

from src.ai.marketing.creative_direction import recommend_theme


def test_premium_positioning_wins_regardless_of_category():
    assert recommend_theme(MagicMock(), "t1", "Home Decor", "PREMIUM") == "LUXURY_PREMIUM"


def test_budget_positioning_wins_regardless_of_category():
    assert recommend_theme(MagicMock(), "t1", "Electronics", "BUDGET") == "BOLD_PROMOTIONAL"


def test_tech_category_keyword_match():
    assert recommend_theme(MagicMock(), "t1", "Consumer Electronics", None) == "MODERN_TECH"


def test_lifestyle_category_keyword_match():
    assert recommend_theme(MagicMock(), "t1", "Home Decor", None) == "LIFESTYLE"


def test_high_market_activity_recommends_social_trendy():
    with patch(
        "src.ai.marketing.creative_direction.market_overview.get_market_overview",
        return_value={"price_trend": {}, "sentiment": {}, "category_activity": {"Toys": "High"}},
    ):
        assert recommend_theme(MagicMock(), "t1", "Toys", None) == "SOCIAL_TRENDY"


def test_low_market_activity_falls_back_to_default():
    with patch(
        "src.ai.marketing.creative_direction.market_overview.get_market_overview",
        return_value={"price_trend": {}, "sentiment": {}, "category_activity": {"Toys": "Low"}},
    ):
        assert recommend_theme(MagicMock(), "t1", "Toys", None) == "MINIMAL_CLEAN"


def test_no_category_and_no_positioning_falls_back_to_default_without_touching_db():
    conn = MagicMock()
    assert recommend_theme(conn, "t1", None, None) == "MINIMAL_CLEAN"
    conn.cursor.assert_not_called()
