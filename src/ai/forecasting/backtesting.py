"""Reproducible rolling-origin historical backtesting for demand forecasts."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from src.ai.forecasting import baselines, evaluation
from src.ai.forecasting.features import build_feature_frame
from src.ai.forecasting.model import DEFAULT_PARAMS, XGBoostDemandForecaster


@dataclass(frozen=True)
class BacktestConfig:
    min_train_rows: int = 30
    max_folds: Optional[int] = 30
    step: int = 1

    def validate(self):
        if self.min_train_rows < 2:
            raise ValueError("min_train_rows must be at least 2")
        if self.max_folds is not None and self.max_folds < 1:
            raise ValueError("max_folds must be positive or None")
        if self.step < 1:
            raise ValueError("step must be positive")


def _paired_arrays(actual, predicted):
    actual_array = np.asarray(actual, dtype=float)
    predicted_array = np.asarray(predicted, dtype=float)
    if actual_array.ndim != 1 or predicted_array.ndim != 1:
        raise ValueError("actual and predicted must be one-dimensional")
    if len(actual_array) == 0 or len(actual_array) != len(predicted_array):
        raise ValueError("actual and predicted must have the same non-zero length")
    if not np.all(np.isfinite(actual_array)) or not np.all(np.isfinite(predicted_array)):
        raise ValueError("actual and predicted must contain only finite values")
    return actual_array, predicted_array


def _mape(actual, predicted) -> float:
    """MAPE on non-zero actual demand; percentage error is undefined at zero."""
    actual, predicted = _paired_arrays(actual, predicted)
    nonzero = actual != 0
    if not np.any(nonzero):
        return float("nan")
    return float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])) * 100)


def _metric_summary(actual, predicted, training_series) -> dict:
    _paired_arrays(actual, predicted)
    return {
        "mae": evaluation.mae(actual, predicted),
        "rmse": evaluation.rmse(actual, predicted),
        "mape": _mape(actual, predicted),
        "mase": evaluation.mase(actual, predicted, training_series),
    }


def validate_daily_history(daily: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "quantity", "avg_unit_price"}
    missing = required - set(daily.columns)
    if missing:
        raise ValueError(f"daily history is missing columns: {', '.join(sorted(missing))}")
    frame = daily[["date", "quantity", "avg_unit_price"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame["quantity"] = pd.to_numeric(frame["quantity"], errors="raise")
    frame["avg_unit_price"] = pd.to_numeric(frame["avg_unit_price"], errors="coerce")
    frame = frame.sort_values("date").reset_index(drop=True)
    if frame.empty or frame["date"].duplicated().any():
        raise ValueError("daily history must contain unique dates")
    if not np.all(np.isfinite(frame["quantity"])) or (frame["quantity"] < 0).any():
        raise ValueError("quantity must contain finite non-negative values")
    expected = pd.date_range(frame["date"].min(), frame["date"].max(), freq="D")
    if len(expected) != len(frame) or not frame["date"].equals(pd.Series(expected)):
        raise ValueError("daily history must have one row for every calendar day")
    frame["avg_unit_price"] = frame["avg_unit_price"].ffill().bfill()
    if frame["avg_unit_price"].isna().all():
        raise ValueError("at least one avg_unit_price is required")
    return frame


def rolling_origins(n_rows: int, config: BacktestConfig) -> list[int]:
    config.validate()
    candidates = list(range(config.min_train_rows, n_rows, config.step))
    if config.max_folds is not None:
        candidates = candidates[-config.max_folds:]
    return candidates


def run_backtest(
    daily: pd.DataFrame,
    config: BacktestConfig = BacktestConfig(),
    model_params: Optional[dict] = None,
    current_price: Optional[float] = None,
    current_stock: Optional[float] = None,
) -> dict:
    """Retrain on each past window and predict the next unseen day without leakage."""
    daily = validate_daily_history(daily)
    history_fingerprint = hashlib.sha256(
        daily.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8")
    ).hexdigest()
    effective_model_params = {
        **DEFAULT_PARAMS, "random_state": 42, **(model_params or {}),
    }
    features = build_feature_frame(daily, current_price, current_stock)
    origins = rolling_origins(len(features), config)
    if not origins:
        raise ValueError(
            f"insufficient usable history: {len(features)} feature rows; "
            f"need more than {config.min_train_rows}"
        )

    records = []
    for test_index in origins:
        train = features.iloc[:test_index]
        test = features.iloc[[test_index]]
        test_date = test["date"].iloc[0]
        history = daily.loc[daily["date"] < test_date, "quantity"]
        candidate_predictions = {
            name: float(values[0])
            for name, values in baselines.all_baseline_forecasts(history, 1).items()
        }
        model = XGBoostDemandForecaster(effective_model_params).fit(train)
        candidate_predictions["model"] = max(0.0, float(model.predict(test)[0]))
        records.append({
            "date": test_date.isoformat(),
            "train_start": train["date"].iloc[0].isoformat(),
            "train_end": train["date"].iloc[-1].isoformat(),
            "train_rows": len(train),
            "actual": float(test["quantity"].iloc[0]),
            **candidate_predictions,
        })

    predictions = pd.DataFrame(records)
    actual = predictions["actual"].to_numpy()
    first_test_date = pd.Timestamp(predictions["date"].iloc[0])
    scale_history = daily.loc[daily["date"] < first_test_date, "quantity"].to_numpy()
    candidates = ["model", *baselines.BASELINE_FUNCTIONS.keys()]
    metrics = {
        name: _metric_summary(actual, predictions[name], scale_history)
        for name in candidates
    }
    ranking = sorted(candidates, key=lambda name: (metrics[name]["mae"], metrics[name]["rmse"]))
    best_baseline = min(baselines.BASELINE_FUNCTIONS, key=lambda name: metrics[name]["mae"])
    baseline_mae = metrics[best_baseline]["mae"]
    improvement = None if baseline_mae == 0 else (
        (baseline_mae - metrics["model"]["mae"]) / baseline_mae * 100
    )
    return {
        "method": "expanding-window one-step rolling-origin backtest",
        "leakage_policy": (
            "Each fold trains only on dates before its test date. The next actual day "
            "becomes history only for the following fold."
        ),
        "config": asdict(config),
        "model_params": effective_model_params,
        "history_sha256": history_fingerprint,
        "n_folds": len(records),
        "evaluation_start": records[0]["date"],
        "evaluation_end": records[-1]["date"],
        "metrics": metrics,
        "ranking_by_mae": ranking,
        "winner": ranking[0],
        "best_baseline": best_baseline,
        "model_beats_all_baselines": ranking[0] == "model",
        "model_mae_improvement_over_best_baseline_percent": improvement,
        "predictions": records,
    }


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_backtest_report(result: dict, output_directory) -> dict:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "summary.json"
    predictions_path = output / "predictions.csv"
    comparison_path = output / "comparison.md"
    safe_result = _json_safe(result)
    summary_path.write_text(
        json.dumps(safe_result, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    pd.DataFrame(result["predictions"]).to_csv(predictions_path, index=False)
    rows = [
        "# Forecast Backtest Comparison", "",
        f"- Method: {result['method']}",
        f"- Evaluation period: {result['evaluation_start']} to {result['evaluation_end']}",
        f"- Folds: {result['n_folds']}",
        f"- Winner by MAE: **{result['winner']}**",
        f"- Best baseline: **{result['best_baseline']}**",
        (
            "- Model MAE improvement over best baseline: "
            f"**{result['model_mae_improvement_over_best_baseline_percent']:.2f}%**"
            if result["model_mae_improvement_over_best_baseline_percent"] is not None
            else "- Model MAE improvement over best baseline: not defined"
        ),
        "",
        "| Candidate | MAE | RMSE | MAPE (%) | MASE |", "|---|---:|---:|---:|---:|",
    ]
    for name in result["ranking_by_mae"]:
        metric = result["metrics"][name]
        rows.append(
            f"| {name} | {metric['mae']:.4f} | {metric['rmse']:.4f} | "
            f"{metric['mape']:.4f} | {metric['mase']:.4f} |"
        )
    comparison_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {
        "summary": str(summary_path), "predictions": str(predictions_path),
        "comparison": str(comparison_path),
    }
