"""
KEEL - Demand Forecasting Pipeline (spec S18, S22, S23, S25).
Orchestrates: load history -> cold-start check -> baseline (+ XGBoost when
enough data) -> pick whichever actually beats the baseline -> persist forecast
+ evidence. This is the only module that writes to the database.
"""

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from src.ai.forecasting import baselines, cold_start, data_access, evaluation, evidence
from src.ai.core.calendar import SATURDAY_SUNDAY, weekend_days
from src.ai.forecasting.features import build_feature_frame
from src.ai.forecasting.model import MODEL_NAME, XGBoostDemandForecaster, expanding_window_splits, walk_forward_validate

logger = logging.getLogger("CEOPRO_AI_FORECASTING_PIPELINE")

SOURCE_MODULE = "ai.forecasting"
MIN_TRAIN_SIZE_FOR_VALIDATION = 14


# A product sold on fewer than this share of recent days is "intermittent":
# day-by-day XGBoost recursion is unreliable there (found in acceptance
# testing: a product sold a handful of times in 90 days got a 95%-confidence
# model forecast), so the period-total baselines decide instead.
INTERMITTENT_ZERO_DAY_SHARE = 0.6
_TOTAL_BACKTEST_WINDOWS = 4
BLEND_MIN_HISTORY_DAYS = 60


def _best_baseline(history: pd.Series, horizon_days: int, with_error: bool = False) -> tuple:
    """Picks the baseline that best predicted past horizon TOTALS (the number
    the forecast is used for) over up to four rolling windows; falls back to
    one-step in-sample error when there isn't two horizons of history.
    Returns (name, horizon_forecast)."""
    windows = min(_TOTAL_BACKTEST_WINDOWS, len(history) // horizon_days - 1)
    if len(history) >= BLEND_MIN_HISTORY_DAYS and windows >= 1:
        # Enough history: the recent blend (see baselines.recent_blend_forecast).
        # Its backtested error is what any model has to beat.
        fn = baselines.BASELINE_FUNCTIONS["recent_blend"]
        misses = []
        for k in range(1, windows + 1):
            origin = len(history) - k * horizon_days
            misses.append(abs(float(np.sum(fn(history.iloc[:origin], horizon_days))) - float(history.iloc[origin:origin + horizon_days].sum())))
        forecast = fn(history, horizon_days)
        return ("recent_blend", forecast, float(np.mean(misses))) if with_error else ("recent_blend", forecast)
    if windows >= 1:
        errors = {}
        for name, fn in baselines.BASELINE_FUNCTIONS.items():
            misses = []
            for k in range(1, windows + 1):
                origin = len(history) - k * horizon_days
                predicted_total = float(np.sum(fn(history.iloc[:origin], horizon_days)))
                actual_total = float(history.iloc[origin:origin + horizon_days].sum())
                misses.append(abs(predicted_total - actual_total))
            errors[name] = float(np.mean(misses))
        best_name = min(errors, key=errors.get)
        forecast = baselines.BASELINE_FUNCTIONS[best_name](history, horizon_days)
        return (best_name, forecast, errors[best_name]) if with_error else (best_name, forecast)

    if len(history) < 2:
        name = "naive"
        forecast = baselines.BASELINE_FUNCTIONS[name](history, horizon_days)
        return (name, forecast, None) if with_error else (name, forecast)

    scores = {}
    for name in baselines.BASELINE_FUNCTIONS:
        preds = baselines.baseline_in_sample_predictions(history, name)
        actual = history.iloc[1:].to_numpy()
        scores[name] = evaluation.mae(actual, preds) if preds else float("inf")

    best_name = min(scores, key=scores.get)
    horizon_forecast = baselines.BASELINE_FUNCTIONS[best_name](history, horizon_days)
    return (best_name, horizon_forecast, None) if with_error else (best_name, horizon_forecast)


# The model must also win on what it is used for: the TOTAL over the next
# horizon, produced recursively from its own predictions. Winning one-day-
# ahead validation (with true lags) is not enough - recursive errors compound
# and, in acceptance testing, pulled several 30-day forecasts 20-30% below
# every recent month while the one-step score said the model was better.
_MODEL_TOTAL_BACKTEST_WINDOWS = 2


def _xgboost_total_backtest_error(daily: pd.DataFrame, current_price, current_stock, horizon_days: int, weekend) -> Optional[float]:
    misses = []
    for k in range(1, _MODEL_TOTAL_BACKTEST_WINDOWS + 1):
        origin = len(daily) - k * horizon_days
        if origin <= 0:
            break
        train = daily.iloc[:origin].reset_index(drop=True)
        frame = build_feature_frame(train, current_price, current_stock, weekend)
        if len(frame) < MIN_TRAIN_SIZE_FOR_VALIDATION + cold_start.MIN_VALIDATION_FOLDS:
            break
        model = XGBoostDemandForecaster().fit(frame)
        predicted = _recursive_xgboost_forecast(model, train, current_price, current_stock, horizon_days, weekend)
        if len(predicted) != horizon_days:
            break
        actual_total = float(daily["quantity"].iloc[origin:origin + horizon_days].sum())
        misses.append(abs(float(np.sum(predicted)) - actual_total))
    return float(np.mean(misses)) if misses else None


def _recursive_xgboost_forecast(
    forecaster: XGBoostDemandForecaster,
    daily_history: pd.DataFrame,
    current_price: Optional[float],
    current_stock: Optional[float],
    horizon_days: int,
    weekend=SATURDAY_SUNDAY,
) -> np.ndarray:
    """
    Lag/rolling features mean a tree model can only predict one day at a time.
    Predicts one step, appends it to the working series, rebuilds features, and
    repeats until `horizon_days` steps are produced.
    """
    working = daily_history[["date", "quantity", "avg_unit_price"]].copy()
    predictions = []

    for _ in range(horizon_days):
        feature_frame = build_feature_frame(working, current_price, current_stock, weekend)
        if feature_frame.empty:
            break
        next_features = feature_frame.iloc[[-1]]
        next_prediction = float(forecaster.predict(next_features)[0])
        next_prediction = max(0.0, next_prediction)  # demand can't be negative
        predictions.append(next_prediction)

        next_date = working["date"].iloc[-1] + timedelta(days=1)
        next_row = {
            "date": next_date,
            "quantity": next_prediction,
            "avg_unit_price": working["avg_unit_price"].iloc[-1],
        }
        working = pd.concat([working, pd.DataFrame([next_row])], ignore_index=True)

    return np.array(predictions)


def choose_forecast(daily: pd.DataFrame, sufficiency, current_price, current_stock, weekend, horizon_days: int = 30) -> dict:
    """Pure model selection (no database writes): the best baseline by
    backtested horizon totals, replaced by XGBoost only when the model beats
    every baseline in walk-forward validation AND its recursive horizon total
    backtests better than that baseline's."""
    history = daily["quantity"]
    best_baseline_name, baseline_forecast, baseline_total_error = _best_baseline(history, horizon_days, with_error=True)
    result = {"source": "baseline", "name": best_baseline_name, "values": baseline_forecast, "metrics": None,
              "baseline_name": best_baseline_name, "intermittent": False, "model_rejected_on_totals": False}

    min_rows_for_validation = MIN_TRAIN_SIZE_FOR_VALIDATION + cold_start.MIN_VALIDATION_FOLDS
    feature_frame = build_feature_frame(daily, current_price, current_stock, weekend)
    recent = history.tail(90)
    intermittent = len(recent) > 0 and float((recent == 0).mean()) > INTERMITTENT_ZERO_DAY_SHARE
    result["intermittent"] = intermittent
    can_validate = sufficiency.sufficient and len(feature_frame) >= min_rows_for_validation and not intermittent
    if not can_validate:
        return result

    validation = walk_forward_validate(feature_frame, MIN_TRAIN_SIZE_FOR_VALIDATION, cold_start.MIN_VALIDATION_FOLDS)
    baseline_val_predictions = {}
    splits = expanding_window_splits(len(feature_frame), MIN_TRAIN_SIZE_FOR_VALIDATION, cold_start.MIN_VALIDATION_FOLDS)
    for name in baselines.BASELINE_FUNCTIONS:
        in_sample = baselines.baseline_in_sample_predictions(feature_frame["quantity"], name)
        baseline_val_predictions[name] = [in_sample[val_idx[0] - 1] for _, val_idx in splits if val_idx[0] - 1 < len(in_sample)]
    comparison = evaluation.compare_to_baselines(validation["predictions"], validation["actuals"], baseline_val_predictions)
    metrics = {
        "mae": evaluation.mae(validation["actuals"], validation["predictions"]),
        "rmse": evaluation.rmse(validation["actuals"], validation["predictions"]),
        "mase": evaluation.mase(validation["actuals"], validation["predictions"], validation["training_series"]),
        "n_folds": validation["n_folds"],
        "baseline_scores": comparison["scores"],
    }
    result["metrics"] = metrics
    if not comparison["model_beats_all_baselines"]:
        return result

    model_total_error = _xgboost_total_backtest_error(daily, current_price, current_stock, horizon_days, weekend)
    metrics["model_total_error"] = model_total_error
    metrics["baseline_total_error"] = baseline_total_error
    if model_total_error is None or baseline_total_error is None or model_total_error >= baseline_total_error:
        result["model_rejected_on_totals"] = True
        return result

    forecaster = XGBoostDemandForecaster().fit(feature_frame)
    recursive = _recursive_xgboost_forecast(forecaster, daily, current_price, current_stock, horizon_days, weekend)
    if len(recursive) == horizon_days:
        result.update({"source": "xgboost", "name": MODEL_NAME, "values": recursive})
    return result


# Every screen and the restock logic read a forecast as "demand over the next
# 30 days" - see the expected_demand note in run_forecast().
DEFAULT_HORIZON_DAYS = 30


def run_forecast(conn, tenant_id: str, product_id: str, horizon_days: int = DEFAULT_HORIZON_DAYS) -> dict:
    daily = data_access.load_daily_demand(conn, tenant_id, product_id)

    if daily.empty:
        explanation = "No historical transaction data is available for this product yet."
        evidence_id = evidence.insert_evidence_record(
            conn, tenant_id, "UNKNOWN", SOURCE_MODULE, {"product_id": product_id}, None, explanation, None
        )
        conn.commit()
        logger.info(f"No data for tenant={tenant_id} product={product_id}; recorded UNKNOWN evidence={evidence_id}")
        return {"status": "UNKNOWN", "evidence_id": evidence_id}

    sufficiency = cold_start.assess(daily)
    product_context = data_access.load_product_context(conn, tenant_id, product_id) or {}
    current_price = product_context.get("current_price")
    current_stock = product_context.get("current_stock")
    weekend = weekend_days(product_context.get("country_code"))

    choice = choose_forecast(daily, sufficiency, current_price, current_stock, weekend, horizon_days)
    history = daily["quantity"]
    best_baseline_name = choice["baseline_name"]
    forecast_target_date = daily["date"].iloc[-1].date() + timedelta(days=horizon_days)
    chosen_source, chosen_name = choice["source"], choice["name"]
    forecast_values, metrics = choice["values"], choice["metrics"]
    intermittent = choice["intermittent"]
    trained_model_version_str = None
    if chosen_source == "xgboost":
        trained_model_version_str = date.today().isoformat()
        evidence.insert_model_version(conn, MODEL_NAME, trained_model_version_str, "candidate", metrics)

    # expected_demand is the TOTAL demand over the horizon (units over the
    # next `horizon_days` days). It used to be the single last day's value
    # while every consumer - restock advice ("Predicted 30-day demand vs
    # stock"), the demand page, the assistant - read it as a period total,
    # so a shop selling ~9 bottles a day with 140 in stock was told demand
    # was "94% below stock" and to reduce orders.
    expected_demand = float(np.sum(forecast_values)) if len(forecast_values) else 0.0

    if chosen_source == "xgboost":
        spread = max(metrics["rmse"], 1.0)
        mase_is_valid = metrics["mase"] == metrics["mase"]  # False for NaN
        confidence_score = round(max(0.3, min(0.95, 1 - min(metrics["mase"], 1.0))), 2) if mase_is_valid else 0.5
        baseline_summary = ", ".join(f"{k}={v:.2f}" for k, v in metrics["baseline_scores"].items() if k != "model")
        explanation = (
            f"XGBoost forecast (trained {trained_model_version_str}) outperformed all baselines "
            f"({baseline_summary}) over {metrics['n_folds']} walk-forward validation folds "
            f"(MAE={metrics['mae']:.2f}, MASE={metrics['mase']:.2f})."
        )
    else:
        recent_std = float(history.tail(14).std()) if len(history) > 1 else 0.0
        spread = recent_std if recent_std == recent_std else 0.0
        confidence_score = 0.4 if sufficiency.sufficient else 0.2
        reason = (
            "sales are intermittent (no sales on most recent days)" if intermittent
            else "the model was better one day ahead but not over the 30-day total" if choice["model_rejected_on_totals"]
            else "did not outperform the baseline" if sufficiency.sufficient else "insufficient historical data"
        )
        explanation = (
            f"Using '{best_baseline_name}' baseline forecast because {reason} "
            f"(available_days={sufficiency.available_days}, minimum_required={sufficiency.minimum_required})."
        )

    # `spread` is a one-day error; over a horizon of independent-ish days the
    # total's error grows with sqrt(horizon), not linearly.
    total_spread = spread * float(np.sqrt(max(horizon_days, 1)))
    confidence_range_lower = max(0.0, expected_demand - 1.28 * total_spread)
    confidence_range_upper = expected_demand + 1.28 * total_spread

    forecast_start_date = daily["date"].iloc[-1].date() + timedelta(days=1)
    demand_forecasts_id = evidence.insert_demand_forecast(
        conn, tenant_id, product_id, expected_demand, confidence_range_lower, confidence_range_upper,
        forecast_target_date, chosen_name,
        forecast_start_date=forecast_start_date,
        features_used={
            "method": chosen_source,
            "daily": [round(float(value), 3) for value in forecast_values],
            "confidence_score": confidence_score,
        },
    )

    evidence_id = evidence.insert_evidence_record(
        conn,
        tenant_id,
        "PREDICTION",
        SOURCE_MODULE,
        {"forecast_id": demand_forecasts_id, "product_id": product_id},
        confidence_score,
        explanation,
        chosen_name,
    )

    conn.commit()
    logger.info(
        f"Forecast written tenant={tenant_id} product={product_id} "
        f"source={chosen_source} forecast_id={demand_forecasts_id}"
    )

    return {
        "status": "OK",
        "source": chosen_source,
        "forecast_id": demand_forecasts_id,
        "evidence_id": evidence_id,
        "expected_demand": expected_demand,
        "horizon_days": horizon_days,
        "average_daily_demand": round(expected_demand / horizon_days, 3) if horizon_days else None,
        "forecast_target_date": forecast_target_date.isoformat(),
        "confidence_score": confidence_score,
        "data_sufficiency": sufficiency.as_dict(),
    }
