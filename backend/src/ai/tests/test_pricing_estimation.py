from unittest.mock import patch

import pytest

from src.ai.pricing import estimation


def _product(pid, category, cost, prices, currency="JOD"):
    return {"product_id": pid, "category": category, "cost": cost, "current_price": 10.0, "currency": currency, "prices": prices}


def test_regional_factor_is_median_of_local_over_foreign_ratios():
    snapshot = [
        _product("a", "x", 5, [(20.0, "JOD"), (10.0, "USD")]),  # local 20 / foreign 10 -> 2.0
        _product("b", "x", 5, [(30.0, "JOD"), (10.0, "USD")]),  # 3.0
        _product("c", "x", 5, [(24.0, "JOD"), (10.0, "USD")]),  # 2.4
    ]
    with patch.object(estimation, "convert_amount", side_effect=lambda conn, amount, f, t: amount):
        factor, samples = estimation.learn_regional_factor(None, snapshot, "JOD")
    assert samples == 3
    assert factor == pytest.approx(2.4)


def test_regional_factor_defaults_when_no_product_has_both_markets():
    snapshot = [_product("a", "x", 5, [(20.0, "JOD")]), _product("b", "x", 5, [(10.0, "USD")])]
    with patch.object(estimation, "convert_amount", side_effect=lambda conn, amount, f, t: amount):
        factor, samples = estimation.learn_regional_factor(None, snapshot, "JOD")
    assert samples == 0
    assert factor == estimation.DEFAULT_REGIONAL_FACTOR


def test_regional_factor_is_clamped_against_bad_calibration_data():
    snapshot = [_product("a", "x", 5, [(1000.0, "JOD"), (1.0, "USD")])]
    with patch.object(estimation, "convert_amount", side_effect=lambda conn, amount, f, t: amount):
        factor, _ = estimation.learn_regional_factor(None, snapshot, "JOD")
    assert factor == estimation.MAX_REGIONAL_FACTOR


def test_peer_price_prefers_same_category_when_enough_peers():
    snapshot = [
        _product("p1", "tea", 2.0, [(4.0, "JOD")]),   # 2.0x
        _product("p2", "tea", 3.0, [(6.0, "JOD")]),   # 2.0x
        _product("p3", "gear", 1.0, [(5.0, "JOD")]),  # 5.0x
    ]
    price, peers, scope = estimation.peer_market_price(snapshot, "target", "tea", 10.0, "JOD")
    assert (price, peers, scope) == (20.0, 2, "same-category")


def test_peer_price_falls_back_to_catalog_wide_and_none_without_cost_or_peers():
    snapshot = [_product("p1", "gear", 2.0, [(6.0, "JOD")])]
    assert estimation.peer_market_price(snapshot, "target", "tea", 10.0, "JOD") == (30.0, 1, "catalog-wide")
    assert estimation.peer_market_price(snapshot, "target", "tea", None, "JOD") is None
    assert estimation.peer_market_price([], "target", "tea", 10.0, "JOD") is None


def test_convert_amount_uses_a_pivot_currency_when_no_direct_rate():
    class R:
        def __init__(self, v):
            self.converted_amount = v

    def fake_convert(conn, amount, f, t):
        return {("SAR", "USD"): R(amount * 0.27), ("USD", "JOD"): R(amount * 0.71)}.get((f, t))

    with patch.object(estimation.currency_service, "convert", side_effect=fake_convert):
        assert estimation.convert_amount(None, 100.0, "SAR", "JOD") == pytest.approx(19.17)
        assert estimation.convert_amount(None, 100.0, "XXX", "JOD") is None
