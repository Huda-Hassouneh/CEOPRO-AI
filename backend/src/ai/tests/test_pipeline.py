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


@pytest.mark.parametrize("values", [[1.0, 2.0], [1.0, float("nan"), 2.0], [1.0, -1.0, 2.0]])
def test_incomplete_or_invalid_model_output_is_not_persisted(fake_conn, values):
    history = _daily(40)
    choice = {
        "source": "baseline", "name": "test", "values": values, "metrics": None,
        "baseline_name": "test", "intermittent": False, "model_rejected_on_totals": False,
    }
    with patch.object(pipeline.data_access, "load_daily_demand", return_value=history), \
         patch.object(pipeline.data_access, "load_product_context", return_value=PRODUCT_CONTEXT), \
         patch.object(pipeline, "choose_forecast", return_value=choice), \
         patch.object(pipeline.evidence, "insert_demand_forecast") as persist:
        with pytest.raises(ValueError, match="incomplete or invalid horizon"):
            pipeline.run_forecast(fake_conn, "tenant-1", "product-1", horizon_days=3)
    persist.assert_not_called()


def test_invalid_horizon_is_rejected_before_database_or_model_work(fake_conn):
    with patch.object(pipeline.data_access, "load_daily_demand") as load:
        with pytest.raises(ValueError, match="horizon"):
            pipeline.run_forecast(fake_conn, "tenant-1", "product-1", horizon_days=0)
    load.assert_not_called()
