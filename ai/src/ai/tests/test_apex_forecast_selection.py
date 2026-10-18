"""Forecast selection is judged on what the forecast is used for: the total
over the next 30 days."""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.ai.forecasting import baselines, cold_start, pipeline


def _daily(values):
    start = date(2026, 1, 1)
    return pd.DataFrame({
        "date": pd.to_datetime([start + timedelta(days=i) for i in range(len(values))]),
        "quantity": [float(v) for v in values],
        "avg_unit_price": [5.0] * len(values),
    })


def test_recent_blend_is_the_average_of_three_recent_rates():
    history = pd.Series([0.0] * 30 + [10.0] * 30)   # last 30 days: 10/day, the 30 before: 0
    forecast = baselines.recent_blend_forecast(history, 30)
    # rates: last 30 -> 10, last 28 -> 10, last 60 -> 5  => 8.33/day
    assert np.isclose(forecast.sum(), 30 * (10 + 10 + 5) / 3)


def test_enough_history_uses_the_recent_blend_and_reports_its_backtest_error():
    rng = np.random.default_rng(1)
    history = pd.Series(rng.poisson(12, 120).astype(float))
    name, forecast, error = pipeline._best_baseline(history, 30, with_error=True)
    assert name == "recent_blend"
    assert len(forecast) == 30 and error is not None and error >= 0


def test_short_history_keeps_the_per_baseline_selection():
    history = pd.Series([5.0] * 40)
    name, _forecast = pipeline._best_baseline(history, 30)
    assert name != "recent_blend"


def test_model_that_loses_on_30_day_totals_is_not_used(monkeypatch):
    rng = np.random.default_rng(7)
    daily = _daily(rng.poisson(20, 180))
    sufficiency = cold_start.assess(daily)

    class _Comparison:
        pass

    monkeypatch.setattr(pipeline.evaluation, "compare_to_baselines", lambda *a, **k: {"model_beats_all_baselines": True, "scores": {}})
    monkeypatch.setattr(pipeline, "_xgboost_total_backtest_error", lambda *a, **k: 10_000.0)
    choice = pipeline.choose_forecast(daily, sufficiency, 5.0, 100.0, (5, 6), 30)
    assert choice["source"] == "baseline"
    assert choice["model_rejected_on_totals"] is True

    monkeypatch.setattr(pipeline, "_xgboost_total_backtest_error", lambda *a, **k: 0.0)
    choice = pipeline.choose_forecast(daily, sufficiency, 5.0, 100.0, (5, 6), 30)
    assert choice["source"] == "xgboost" and len(choice["values"]) == 30
