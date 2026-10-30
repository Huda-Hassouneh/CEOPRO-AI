"""
Exercises pipeline.run_forecast's branching logic (no data / insufficient data /
sufficient data) with data_access and evidence mocked out, so it runs without a
real database connection while still catching real runtime errors in the
orchestration code (wrong arg counts, bad attribute access, etc.).
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.ai.forecasting import pipeline

PRODUCT_CONTEXT = {"current_price": 20.0, "current_stock": 5}


def _daily(n_days: int, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2026-01-01", periods=n_days)
    weekly_pattern = np.where(np.isin(dates.dayofweek, [4, 5]), 18.0, 10.0)
    quantity = np.clip(weekly_pattern + rng.normal(0, 1.5, size=n_days), 0, None)
    return pd.DataFrame({"date": dates, "quantity": quantity, "avg_unit_price": 20.0})


@pytest.fixture
def fake_conn():
    return MagicMock()


def test_no_history_records_unknown_evidence(fake_conn):
    empty_history = pd.DataFrame(columns=["date", "quantity", "avg_unit_price"])
    with patch.object(pipeline.data_access, "load_daily_demand", return_value=empty_history), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence:
        result = pipeline.run_forecast(fake_conn, "tenant-1", "product-1", horizon_days=7)

    assert result == {"status": "UNKNOWN", "evidence_id": "evidence-1"}
    mock_evidence.assert_called_once()
    assert mock_evidence.call_args.args[2] == "UNKNOWN"
    fake_conn.commit.assert_called_once()


def test_insufficient_history_falls_back_to_baseline(fake_conn):
    short_history = _daily(10)

    with patch.object(pipeline.data_access, "load_daily_demand", return_value=short_history), \
         patch.object(pipeline.data_access, "load_product_context", return_value=PRODUCT_CONTEXT), \
         patch.object(pipeline.evidence, "insert_demand_forecast", return_value="forecast-1") as mock_forecast, \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence, \
         patch.object(pipeline.evidence, "insert_model_version") as mock_model_version:
        result = pipeline.run_forecast(fake_conn, "tenant-1", "product-1", horizon_days=3)

    assert result["status"] == "OK"
    assert result["source"] == "baseline"
    assert result["data_sufficiency"]["sufficient"] is False
    mock_forecast.assert_called_once()
    mock_evidence.assert_called_once()
    mock_model_version.assert_not_called()  # no model trained on the cold-start path


def test_sufficient_history_can_train_and_use_xgboost(fake_conn):
    long_history = _daily(90)

    with patch.object(pipeline.data_access, "load_daily_demand", return_value=long_history), \
         patch.object(pipeline.data_access, "load_product_context", return_value=PRODUCT_CONTEXT), \
         patch.object(pipeline.evidence, "insert_demand_forecast", return_value="forecast-1") as mock_forecast, \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1") as mock_evidence, \
         patch.object(pipeline.evidence, "insert_model_version", return_value="model-1") as mock_model_version:
        result = pipeline.run_forecast(fake_conn, "tenant-1", "product-1", horizon_days=7)

    assert result["status"] == "OK"
    assert result["source"] in ("baseline", "xgboost")  # xgboost only if it actually beat every baseline on this run
    assert result["data_sufficiency"]["sufficient"] is True
    mock_forecast.assert_called_once()
    mock_evidence.assert_called_once()
    if result["source"] == "xgboost":
        mock_model_version.assert_called_once()
    else:
        mock_model_version.assert_not_called()


def test_expected_demand_is_the_total_over_the_horizon_not_one_day(fake_conn):
    """Restock advice and every screen read expected_demand as demand over the
    next 30 days; it used to be the single last day's value (~1/30 of that)."""
    steady = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=20), "quantity": 10.0, "avg_unit_price": 20.0})
    with patch.object(pipeline.data_access, "load_daily_demand", return_value=steady), \
         patch.object(pipeline.data_access, "load_product_context", return_value=PRODUCT_CONTEXT), \
         patch.object(pipeline.evidence, "insert_demand_forecast", return_value="forecast-1") as mock_forecast, \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1"):
        result = pipeline.run_forecast(fake_conn, "tenant-1", "product-1")

    assert result["horizon_days"] == 30
    assert result["expected_demand"] == pytest.approx(300.0)
    assert result["average_daily_demand"] == pytest.approx(10.0)
    assert mock_forecast.call_args.args[3] == pytest.approx(300.0)


def test_slow_intermittent_seller_gets_a_realistic_monthly_total_not_zero(fake_conn):
    """Sold ~once every 3 days (about 10 a month): 'repeat the last day/week'
    baselines predicted 0 for the month whenever the last week was quiet."""
    quantity = [1.0 if i % 3 == 0 else 0.0 for i in range(200)]
    quantity[-7:] = [0.0] * 7  # a quiet last week
    sparse = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=200), "quantity": quantity, "avg_unit_price": 5.0})
    with patch.object(pipeline.data_access, "load_daily_demand", return_value=sparse), \
         patch.object(pipeline.data_access, "load_product_context", return_value=PRODUCT_CONTEXT), \
         patch.object(pipeline.evidence, "insert_demand_forecast", return_value="forecast-1"), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1"), \
         patch.object(pipeline.evidence, "insert_model_version") as mock_model_version:
        result = pipeline.run_forecast(fake_conn, "tenant-1", "product-1")

    assert result["source"] == "baseline"  # no daily model on an intermittent series
    mock_model_version.assert_not_called()
    assert 6 <= result["expected_demand"] <= 14


def test_quiet_last_fortnight_does_not_collapse_the_range_of_an_irregular_seller(fake_conn):
    """Sold 1-20 units on scattered days, nothing in the last 14: the range was
    lower == upper (the 14-day std is 0), which reads as a certain forecast."""
    quantity = [0.0] * 120
    for day, units in [(5, 1.0), (19, 20.0), (33, 1.0), (47, 5.0), (61, 1.0), (75, 20.0), (89, 1.0), (103, 5.0)]:
        quantity[day] = units
    sparse = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=120), "quantity": quantity, "avg_unit_price": 3.0})
    with patch.object(pipeline.data_access, "load_daily_demand", return_value=sparse), \
         patch.object(pipeline.data_access, "load_product_context", return_value=PRODUCT_CONTEXT), \
         patch.object(pipeline.evidence, "insert_demand_forecast", return_value="forecast-1") as mock_forecast, \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1"):
        pipeline.run_forecast(fake_conn, "tenant-1", "product-1")

    expected, lower, upper = mock_forecast.call_args.args[3:6]
    assert lower <= expected <= upper
    assert upper - lower > 0


# --- isolated extreme days (decision-safety test, docs/SECURITY_MULTI_TENANT_TEST.md) -------------------

def test_one_mistyped_day_is_capped_and_named_in_the_explanation(fake_conn):
    daily = _daily(120)
    with patch.object(pipeline.data_access, "load_daily_demand", return_value=daily.copy()), \
         patch.object(pipeline.data_access, "load_product_context", return_value=PRODUCT_CONTEXT), \
         patch.object(pipeline.evidence, "insert_demand_forecast", return_value="f-0"), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="e-0"), \
         patch.object(pipeline.evidence, "insert_model_version"):
        clean = pipeline.run_forecast(fake_conn, "tenant-1", "product-1")
    typo = daily.copy()
    typo.loc[typo.index[-2], "quantity"] = 50_000.0
    with patch.object(pipeline.data_access, "load_daily_demand", return_value=typo), \
         patch.object(pipeline.data_access, "load_product_context", return_value=PRODUCT_CONTEXT), \
         patch.object(pipeline.evidence, "insert_demand_forecast", return_value="f-1"), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="e-1") as mock_evidence, \
         patch.object(pipeline.evidence, "insert_model_version"):
        result = pipeline.run_forecast(fake_conn, "tenant-1", "product-1")

    assert [d["quantity"] for d in result["capped_outlier_days"]] == [50_000.0]
    # Without the cap this forecast was over 40,000 units; with it, it stays near the clean one.
    assert result["expected_demand"] < clean["expected_demand"] * 2
    explanation = mock_evidence.call_args.args[6]
    assert "50000" in explanation and "typing error" in explanation


def test_a_real_surge_over_many_days_is_not_capped():
    daily = _daily(120)
    daily.loc[daily.index[-10:], "quantity"] = 400.0  # ten days of a genuine new demand level
    capped, days = pipeline.cap_isolated_outliers(daily)
    assert days == [] and capped["quantity"].iloc[-1] == 400.0


def test_too_little_history_is_never_capped():
    daily = _daily(10)
    daily.loc[daily.index[-1], "quantity"] = 5_000.0
    assert pipeline.cap_isolated_outliers(daily)[1] == []
