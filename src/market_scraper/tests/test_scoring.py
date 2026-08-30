import pytest

from src.market_scraper.scoring import (
    alert_matches,
    composite_score,
    expansion_opportunity,
    market_activity,
    price_competitiveness,
    relevance_score,
)


def test_price_competitiveness_is_1_to_10_dashboard_scale_as_percentage():
    assert price_competitiveness(100, 100).value == 100.0
    assert price_competitiveness(150, 100).value == 10.0
    assert price_competitiveness(None, 100).missing_factors == ("price",)


def test_scores_renormalize_available_evidence_and_report_missing_factors():
    relevance = relevance_score(product=90, category=70, brand=None)
    assert relevance.value == 80.0
    assert relevance.missing_factors == ("brand",)

    composite = composite_score(price=80, sentiment=None, activity=40)
    assert composite.value == pytest.approx(67.69, abs=0.01)
    assert composite.missing_factors == ("sentiment",)


def test_activity_alerts_and_expansion_are_bounded():
    assert market_activity(1000, 1000) == 100.0
    assert alert_matches("GTE", 10, 10)
    assert not alert_matches("LT", 10, 10)
    with pytest.raises(ValueError, match="unsupported"):
        alert_matches("NOPE", 1, 2)
    assert 0 <= expansion_opportunity(4, 4.5, 30, 0.9).value <= 100
