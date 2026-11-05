"""The stored forecast range reflects how much past horizon totals actually missed by."""
import numpy as np
import pandas as pd

from src.ai.forecasting import pipeline


def _choice(name="recent_blend"):
    return {"source": "baseline", "name": name, "baseline_name": name, "metrics": None}


def test_a_trending_product_gets_a_range_as_wide_as_its_past_misses():
    # Steady growth: each day's noise is small, but every past 30-day total was missed by a lot.
    history = pd.Series(np.arange(200, dtype=float) * 0.2 + 5)
    expected = float(np.sum(pipeline.baselines.recent_blend_forecast(history, 30)))
    lower, upper = pipeline.forecast_interval(_choice(), history, expected, 30)
    misses = pipeline._horizon_total_errors(history, "recent_blend", 30)
    assert len(misses) >= pipeline._INTERVAL_MIN_WINDOWS
    assert upper - expected >= np.quantile(misses, 0.8) - 1e-9
    assert np.isclose(lower, max(0.0, expected - (upper - expected)))


def test_short_history_keeps_the_one_day_error_range():
    history = pd.Series([3.0, 5.0, 4.0, 6.0, 5.0] * 8)  # 40 days: too few past windows to measure
    lower, upper = pipeline.forecast_interval(_choice(), history, 150.0, 30)
    half = 1.28 * float(history.tail(14).std()) * np.sqrt(30)
    assert np.isclose(upper - 150.0, half) and np.isclose(150.0 - lower, half)


def test_range_never_goes_below_zero():
    history = pd.Series([0.0] * 150 + [40.0] * 30)
    lower, _ = pipeline.forecast_interval(_choice(), history, 10.0, 30)
    assert lower == 0.0
