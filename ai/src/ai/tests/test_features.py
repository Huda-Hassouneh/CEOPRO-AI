import pandas as pd

from src.ai.forecasting.features import build_feature_frame, feature_columns


def _sample_daily(n_days: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=n_days),
            "quantity": [float(i % 10) for i in range(n_days)],
            "avg_unit_price": [15.0] * n_days,
        }
    )


def test_drops_rows_without_full_lag_history():
    daily = _sample_daily(20)
    result = build_feature_frame(daily)
    # first 14 rows can't have a full 14-day lag/rolling window
    assert len(result) == 20 - 14


def test_output_contains_all_expected_feature_columns():
    daily = _sample_daily(30)
    result = build_feature_frame(daily, current_price=9.99, current_stock=42)
    for column in feature_columns():
        assert column in result.columns
    assert (result["current_stock"] == 42).all()


def test_empty_input_returns_empty_frame():
    daily = _sample_daily(5)  # fewer than required lag window
    result = build_feature_frame(daily)
    assert result.empty


def test_weekend_flag_follows_the_tenant_country():
    """Was hard-coded to Fri/Sat for every tenant."""
    from src.ai.core.calendar import weekend_days
    daily = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=40, freq="D"),
        "quantity": [float(i % 5) for i in range(40)],
        "avg_unit_price": [10.0] * 40,
    })
    jordan = build_feature_frame(daily, weekend=weekend_days("JO"))
    france = build_feature_frame(daily, weekend=weekend_days("fr"))
    saturday_sunday = {5, 6}
    friday_saturday = {4, 5}
    assert set(france.loc[france["is_weekend"] == 1, "day_of_week"]) == saturday_sunday
    assert set(jordan.loc[jordan["is_weekend"] == 1, "day_of_week"]) == friday_saturday
    assert weekend_days(None) == saturday_sunday and weekend_days("AE") == saturday_sunday
