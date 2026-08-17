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


def _force_xgboost_win(long_history_len: int = 90):
    """
    Whether XGBoost actually beats every baseline depends on random data, so
    tests that specifically need the XGBoost-trained path force it by
    patching the comparison result, rather than relying on chance.
    """
    return patch.object(
        pipeline.evaluation,
        "compare_to_baselines",
        return_value={"model_beats_all_baselines": True, "scores": {"naive": 1.0, "model": 0.5}},
    )


def test_xgboost_training_uploads_artifact_when_minio_client_provided(fake_conn):
    long_history = _daily(90)
    fake_minio = MagicMock()

    with patch.object(pipeline.data_access, "load_daily_demand", return_value=long_history), \
         patch.object(pipeline.data_access, "load_product_context", return_value=PRODUCT_CONTEXT), \
         patch.object(pipeline.evidence, "insert_demand_forecast", return_value="forecast-1"), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1"), \
         patch.object(pipeline.evidence, "insert_model_version", return_value="model-1") as mock_model_version, \
         _force_xgboost_win():
        result = pipeline.run_forecast(fake_conn, "tenant-1", "product-1", horizon_days=7, minio_client=fake_minio)

    assert result["source"] == "xgboost"
    fake_minio.put_object.assert_called_once()
    bucket, object_key = fake_minio.put_object.call_args.args[0], fake_minio.put_object.call_args.args[1]
    assert bucket == pipeline.DEFAULT_ARTIFACTS_BUCKET
    assert object_key.startswith("tenant_tenant-1/models/")
    assert object_key.endswith(".bin")
    artifact_path_arg = mock_model_version.call_args.args[-1]
    assert artifact_path_arg == object_key


def test_xgboost_training_skips_upload_when_no_minio_client(fake_conn):
    long_history = _daily(90)

    with patch.object(pipeline.data_access, "load_daily_demand", return_value=long_history), \
         patch.object(pipeline.data_access, "load_product_context", return_value=PRODUCT_CONTEXT), \
         patch.object(pipeline.evidence, "insert_demand_forecast", return_value="forecast-1"), \
         patch.object(pipeline.evidence, "insert_evidence_record", return_value="evidence-1"), \
         patch.object(pipeline.evidence, "insert_model_version", return_value="model-1") as mock_model_version, \
         _force_xgboost_win():
        result = pipeline.run_forecast(fake_conn, "tenant-1", "product-1", horizon_days=7)

    assert result["source"] == "xgboost"
    assert mock_model_version.call_args.args[-1] is None  # no minio_client -> no artifact_path
