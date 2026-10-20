"""Premium bands per category, added-value guidance, and the plain-language ladder lines. Pure - no database."""
import pytest

from src.ai.pricing import comparisons, premium_bands
from src.market_scraper.price_comparison import tiers


def test_a_category_with_too_few_comparisons_keeps_the_default_band():
    band = premium_bands.derive_band([30, 40, 50, 60])
    assert band == {"band_pct": tiers.PREMIUM_BAND_PCT, "source": "default", "samples": 4}


def test_enough_comparisons_set_the_band_at_their_75th_percentile():
    band = premium_bands.derive_band([10, 20, 30, 40, 50])
    assert band["source"] == "observed" and band["samples"] == 5 and band["band_pct"] == 40.0


def test_the_observed_band_stays_inside_sane_limits():
    assert premium_bands.derive_band([400] * 6)["band_pct"] == premium_bands.MAX_BAND_PCT
    assert premium_bands.derive_band([3] * 6)["band_pct"] == premium_bands.MIN_BAND_PCT


def test_underpriced_premiums_do_not_count_as_samples():
    assert premium_bands.derive_band([0, 1, 2, -5, -10, 1.5])["source"] == "default"


def test_a_stored_premium_is_re_read_against_the_category_band():
    stored = {"premium_pct": 45.0, "status": "within_range", "band_pct": 60}
    out = premium_bands.apply_band(stored, {"band_pct": 30.0, "source": "observed", "samples": 8})
    assert out["status"] == "above_range" and out["band_pct"] == 30.0 and out["band_samples"] == 8


def test_guidance_gives_a_range_not_a_price():
    items = [{"comparable_price": 10.0}, {"comparable_price": 12.0}]
    g = premium_bands.guidance(14.0, items, {"band_pct": 50.0, "source": "observed", "samples": 9})
    assert g["kind"] == "range_not_a_price" and g["base_price"] == 11.0
    assert g["range_low"] == pytest.approx(11.22) and g["range_high"] == pytest.approx(16.5)
    assert g["position"] == "within_range"
    assert premium_bands.guidance(20.0, items, {"band_pct": 50.0, "source": "default", "samples": 0})["position"] == "above_range"
    assert premium_bands.guidance(11.0, items, {"band_pct": 50.0, "source": "default", "samples": 0})["position"] == "below_range"
    assert premium_bands.guidance(14.0, [], {"band_pct": 50.0, "source": "default", "samples": 0}) is None


def _row(tier, price, **extra):
    return {"tier": tier, "competitor_id": "c", "competitor_name": "A", "item_name": "x", "competitor_price": price,
            "scale_factor": 1.0, "comparable_price": price, "currency": "JOD", "price_delta_pct": None, "direction": "same",
            "match_score": 0.8, "reasons": [], "premium": None, "source_url": None, "observed_at": None, **extra}


PRODUCT = {"product_id": "p", "current_price": 14.0, "currency": "JOD"}


def test_guidance_only_appears_when_added_value_is_all_there_is():
    added = _row("ADDED_VALUE", 10.0, premium={"premium_pct": 40.0, "status": "within_range", "band_pct": 60})
    only = comparisons.build_ladder(PRODUCT, [added], [])
    assert only["added_value_guidance"]["base_price"] == 10.0
    mixed = comparisons.build_ladder(PRODUCT, [added, _row("EXACT", 13.0)], [])
    assert mixed["added_value_guidance"] is None


def test_the_category_band_changes_the_premium_status_in_the_ladder():
    added = _row("ADDED_VALUE", 10.0, premium={"premium_pct": 40.0, "status": "within_range", "band_pct": 60})
    ladder = comparisons.build_ladder(PRODUCT, [added], [], {"band_pct": 25.0, "source": "observed", "samples": 7})
    assert ladder["tiers"]["ADDED_VALUE"]["items"][0]["premium"]["status"] == "above_range"
    assert ladder["premium_band"]["band_pct"] == 25.0


def test_ladder_lines_never_call_a_similar_or_added_value_item_an_exact_price():
    ladder = comparisons.build_ladder(PRODUCT, [_row("SIMILAR", 12.0), _row("ADDED_VALUE", 10.0)], [])
    text = comparisons.describe({"name": "Burger", **ladder})
    assert "a reference, not like for like" in text and "added-value" in text
    assert "exact" not in text.lower().replace("not like for like", "")


def test_overview_failure_leaves_the_callers_transaction_alone():
    from unittest.mock import MagicMock, patch

    conn = MagicMock()
    with patch.object(comparisons, "overview_lines", side_effect=RuntimeError("boom")):
        assert comparisons.safe_overview_lines(conn, "t") == []
    sql = [c.args[0] for c in conn.cursor.return_value.__enter__.return_value.execute.call_args_list]
    assert sql == ["SAVEPOINT price_ladder_overview;", "ROLLBACK TO SAVEPOINT price_ladder_overview;"]
    conn.rollback.assert_not_called()
    with patch.object(comparisons, "overview_lines", return_value=["x"]):
        assert comparisons.safe_overview_lines(MagicMock(), "t") == ["x"]
