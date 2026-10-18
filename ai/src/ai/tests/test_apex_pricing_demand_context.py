"""Price advice weighs demand and stock, not only the competitor average."""
from unittest.mock import MagicMock

import pytest

from src.ai.pricing import pipeline


@pytest.fixture
def run(monkeypatch):
    def _run(current_price, competitor_prices, demand, cost=1.0):
        monkeypatch.setattr(pipeline.data_access, "load_own_product", lambda *a: {"product_name": "Oil", "current_price": current_price, "currency": "JOD", "cost": cost})
        monkeypatch.setattr(pipeline.data_access, "load_competitor_prices", lambda *a, **k: [
            {"price_found": p, "price_entry_id": f"e{i}"} for i, p in enumerate(competitor_prices)])
        monkeypatch.setattr(pipeline, "_build_cross_currency_reference", lambda *a: "")
        monkeypatch.setattr(pipeline.evidence, "insert_evidence_record", lambda *a, **k: "ev")
        monkeypatch.setattr(pipeline.evidence, "insert_recommendation_outcome", lambda *a, **k: "out")
        monkeypatch.setattr(pipeline, "_demand_context", lambda *a: demand)
        return pipeline.run_price_recommendation(MagicMock(), "t", "p")
    return _run


def _demand(**overrides):
    base = {"sold_last_30": 100, "sold_previous_30": 100, "sales_change_pct": 0.0, "forecast_next_30": 100,
            "trend": "stable", "stock": 500, "stock_action": "monitor", "days_of_cover": 150}
    return {**base, **overrides}


def test_overpriced_with_healthy_stock_and_flat_demand_is_told_to_lower(run):
    result = run(10.0, [9.0, 9.0, 9.0], _demand())
    assert result["action"] == "lower" and result["hold_reason"] is None
    assert result["suggested_price"] < 10.0


def test_overpriced_but_running_out_holds_the_price(run):
    result = run(10.0, [9.0, 9.0, 9.0], _demand(stock=140, stock_action="restock", days_of_cover=14, forecast_next_30=300))
    assert result["market_action"] == "lower"
    assert result["action"] == "hold" and result["hold_reason"] == "stock_short"
    assert result["suggested_price"] == 10.0
    assert "14 days" in result["explanation"] and "300 units" in result["explanation"]


def test_overpriced_but_selling_faster_holds_the_price(run):
    result = run(10.0, [9.0, 9.0, 9.0], _demand(sold_last_30=130, sold_previous_30=100, sales_change_pct=30.0))
    assert result["action"] == "hold" and result["hold_reason"] == "demand_rising"
    assert "up 30%" in result["explanation"]


def test_underpriced_but_losing_sales_holds_instead_of_raising(run):
    result = run(8.0, [10.0, 10.0], _demand(sold_last_30=60, sold_previous_30=100, sales_change_pct=-40.0))
    assert result["market_action"] == "raise"
    assert result["action"] == "hold" and result["hold_reason"] == "demand_falling"


def test_no_demand_context_falls_back_to_the_market_rule(run):
    result = run(10.0, [9.0, 9.0, 9.0], None)
    assert result["action"] == "lower" and result["demand"] is None
