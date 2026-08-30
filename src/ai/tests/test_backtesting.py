import json

import numpy as np
import pandas as pd
import pytest

from src.ai.forecasting.backtesting import (
    BacktestConfig,
    rolling_origins,
    run_backtest,
    validate_daily_history,
    write_backtest_report,
)


def history(days=100):
    dates = pd.date_range("2025-01-01", periods=days, freq="D")
    quantity = 10 + np.isin(dates.dayofweek, [4, 5]) * 8
    return pd.DataFrame({
        "date": dates, "quantity": quantity.astype(float), "avg_unit_price": 20.0,
    })


def test_rolling_origins_uses_latest_requested_folds():
    config = BacktestConfig(min_train_rows=10, max_folds=3, step=2)
    assert rolling_origins(20, config) == [14, 16, 18]


def test_history_validation_rejects_calendar_gaps_and_negative_demand():
    missing_day = history(30).drop(index=10)
    with pytest.raises(ValueError, match="every calendar day"):
        validate_daily_history(missing_day)
    negative = history(30)
    negative.loc[5, "quantity"] = -1
    with pytest.raises(ValueError, match="non-negative"):
        validate_daily_history(negative)


def test_backtest_retrains_before_each_unseen_date_and_compares_baselines():
    result = run_backtest(
        history(), BacktestConfig(min_train_rows=40, max_folds=8),
        model_params={"n_estimators": 20, "n_jobs": 1}, current_stock=100,
    )
    assert result["n_folds"] == 8
    assert set(result["metrics"]) == {
        "model", "naive", "seasonal_naive", "moving_average", "previous_period",
    }
    assert sorted(result["ranking_by_mae"]) == sorted(result["metrics"])
    assert all(pd.Timestamp(row["train_end"]) < pd.Timestamp(row["date"]) for row in result["predictions"])
    for metric in result["metrics"].values():
        assert set(metric) == {"mae", "rmse", "mape", "mase"}


def test_backtest_is_reproducible_and_writes_machine_and_human_reports(tmp_path):
    config = BacktestConfig(min_train_rows=40, max_folds=4)
    params = {"n_estimators": 10, "n_jobs": 1}
    first = run_backtest(history(), config, params, current_stock=100)
    second = run_backtest(history(), config, params, current_stock=100)
    assert first["metrics"] == second["metrics"]

    paths = write_backtest_report(first, tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    predictions = pd.read_csv(tmp_path / "predictions.csv")
    comparison = (tmp_path / "comparison.md").read_text(encoding="utf-8")
    assert set(paths) == {"summary", "predictions", "comparison"}
    assert summary["n_folds"] == 4
    assert len(predictions) == 4
    assert "| Candidate | MAE | RMSE | MAPE (%) | MASE |" in comparison
