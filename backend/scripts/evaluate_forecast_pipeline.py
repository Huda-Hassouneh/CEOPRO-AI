"""Backtest the production demand-forecast choice on horizon totals, by segment.

Unlike scripts/evaluate_forecasting.py (one-step XGBoost vs baselines on one
series), this scores what customers actually receive: `pipeline.choose_forecast`
(baseline / XGBoost selection, outlier capping, intermittent handling) and the
stored 80% range from `pipeline.forecast_interval`, on the TOTAL demand over the
horizon, at several rolling origins per series.

Data: deterministic synthetic daily-demand series in documented business
segments (no real customer history exists in this repository). `--split dev`
(seeds 0-5) may be used to diagnose and change the forecaster; `--split test`
(seeds 100-111) is the independent estimate and prints aggregates only.

Usage (from backend/):
    python -m scripts.evaluate_forecast_pipeline --split dev
    python -m scripts.evaluate_forecast_pipeline --split test --json reports/forecasting/pipeline_test.json
"""
import argparse
import json
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai.core.calendar import SATURDAY_SUNDAY  # noqa: E402
from src.ai.forecasting import baselines, cold_start, pipeline  # noqa: E402

SPLITS = {"dev": range(0, 6), "test": range(100, 112)}
HISTORY_DAYS = 240
ORIGINS_BEFORE_END = (90, 60, 30)  # three non-overlapping 30-day test windows per series
PRICE = 10.0


def _weekly(dates: pd.DatetimeIndex, amplitude: float) -> np.ndarray:
    # Friday/Saturday busier (common Jordan/Gulf weekend retail pattern).
    return np.where(np.isin(dates.dayofweek, [4, 5]), 1 + amplitude, 1 - amplitude * 2 / 5)


def make_series(segment: str, seed: int, days: int = HISTORY_DAYS) -> pd.DataFrame:
    rng = np.random.default_rng(seed * 1009 + sum(map(ord, segment)))
    dates = pd.date_range("2025-03-01", periods=days, freq="D")
    t = np.arange(days)
    level = rng.uniform(6, 30)
    if segment == "stable":
        mean = np.full(days, level)
    elif segment == "weekly_seasonal":
        mean = level * _weekly(dates, rng.uniform(0.3, 0.6))
    elif segment == "trend_up":
        mean = level * (1 + rng.uniform(0.002, 0.005) * t) * _weekly(dates, 0.2)
    elif segment == "trend_down":
        mean = level * np.clip(1 - rng.uniform(0.0015, 0.003) * t, 0.15, None) * _weekly(dates, 0.2)
    elif segment == "promo_spikes":
        promo = (t % 30) < 4
        mean = level * _weekly(dates, 0.2) * np.where(promo, 1.8, 1.0)
    elif segment == "intermittent":
        mean = np.where(rng.random(days) < 0.25, rng.uniform(2, 6), 0.0)
    elif segment == "with_outliers":
        mean = level * _weekly(dates, 0.3)
    else:
        raise ValueError(segment)
    quantity = rng.poisson(np.clip(mean, 0, None)).astype(float)
    if segment == "with_outliers":
        for index in rng.choice(np.arange(20, days), size=2, replace=False):
            quantity[index] = quantity[index] * 40 + 200  # a mistyped or one-off bulk row
    return pd.DataFrame({"date": dates, "quantity": quantity, "avg_unit_price": PRICE})


SEGMENTS = ("stable", "weekly_seasonal", "trend_up", "trend_down", "promo_spikes", "intermittent", "with_outliers")


def _ses(history: pd.Series, horizon: int, alpha: float = 0.2) -> np.ndarray:
    level = float(history.iloc[0])
    for value in history.iloc[1:]:
        level = alpha * float(value) + (1 - alpha) * level
    return np.full(horizon, max(level, 0.0))


def _holt_damped(history: pd.Series, horizon: int, alpha: float = 0.2, beta: float = 0.05, phi: float = 0.9) -> np.ndarray:
    weekly = history.rolling(7).mean().dropna()
    if len(weekly) < 3:
        return _ses(history, horizon, alpha)
    level, trend = float(weekly.iloc[0]), float(weekly.iloc[1] - weekly.iloc[0])
    for value in weekly.iloc[1:]:
        previous = level
        level = alpha * float(value) + (1 - alpha) * (level + phi * trend)
        trend = beta * (level - previous) + (1 - beta) * phi * trend
    steps = np.arange(1, horizon + 1)
    damped = np.cumsum(phi ** steps)
    return np.clip(level + damped * trend, 0, None)


COMPARATORS = {
    "naive": lambda h, n: baselines.naive_forecast(h, n),
    "seasonal_naive": lambda h, n: baselines.seasonal_naive_forecast(h, n),
    "moving_average_28": lambda h, n: baselines.moving_average_28_forecast(h, n),
    "ses": _ses,
    "holt_damped": _holt_damped,
}


def run(split: str, horizon: int) -> list:
    rows = []
    for segment in SEGMENTS:
        for seed in SPLITS[split]:
            series = make_series(segment, seed)
            for before_end in ORIGINS_BEFORE_END:
                origin = len(series) - before_end
                train = series.iloc[:origin].reset_index(drop=True)
                actual = float(series["quantity"].iloc[origin:origin + horizon].sum())
                capped, _ = pipeline.cap_isolated_outliers(train)
                started = time.perf_counter()
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    choice = pipeline.choose_forecast(capped, cold_start.assess(capped), PRICE, None,
                                                      SATURDAY_SUNDAY, horizon)
                elapsed = time.perf_counter() - started
                predicted = float(np.sum(choice["values"]))
                lower, upper = pipeline.forecast_interval(choice, capped["quantity"], predicted, horizon)
                # Scale for MASE: mean absolute error of the seasonal-naive horizon total over earlier windows.
                history = train["quantity"]
                scale_errors = []
                for k in range(1, 4):
                    cut = len(history) - k * horizon
                    if cut > 7:
                        scale_errors.append(abs(float(np.sum(baselines.seasonal_naive_forecast(history.iloc[:cut], horizon)))
                                                - float(history.iloc[cut:cut + horizon].sum())))
                row = {"segment": segment, "seed": seed, "origin": origin, "actual": actual, "pipeline": predicted,
                       "source": choice["source"], "name": choice["name"], "lower": lower, "upper": upper,
                       "scale": float(np.mean(scale_errors)) if scale_errors else None, "seconds": elapsed}
                for name, fn in COMPARATORS.items():
                    row[name] = float(np.sum(fn(history, horizon)))
                rows.append(row)
    return rows


def metrics(rows: list, column: str) -> dict:
    actual = np.array([r["actual"] for r in rows])
    predicted = np.array([r[column] for r in rows])
    error = predicted - actual
    nonzero = actual > 0
    scales = np.array([r["scale"] if r["scale"] else np.nan for r in rows])
    return {
        "mae": round(float(np.mean(np.abs(error))), 3),
        "rmse": round(float(np.sqrt(np.mean(error ** 2))), 3),
        "wape_pct": round(float(np.sum(np.abs(error)) / np.sum(actual) * 100), 2) if np.sum(actual) else None,
        "mape_pct": round(float(np.mean(np.abs(error[nonzero] / actual[nonzero])) * 100), 2) if nonzero.any() else None,
        "mase": round(float(np.nanmean(np.abs(error) / scales)), 3) if np.isfinite(scales).any() else None,
        "bias_pct": round(float(np.sum(error) / np.sum(actual) * 100), 2) if np.sum(actual) else None,
    }


def summarize(rows: list) -> dict:
    columns = ["pipeline", *COMPARATORS]
    by_segment = defaultdict(list)
    for row in rows:
        by_segment[row["segment"]].append(row)
    covered = [r["lower"] <= r["actual"] <= r["upper"] for r in rows]
    width = [(r["upper"] - r["lower"]) / r["actual"] for r in rows if r["actual"] > 0]
    sources = defaultdict(int)
    for row in rows:
        sources[row["source"]] += 1
    seconds = sorted(r["seconds"] for r in rows)
    return {
        "windows": len(rows),
        "overall": {c: metrics(rows, c) for c in columns},
        "segments": {seg: {c: metrics(seg_rows, c) for c in columns} for seg, seg_rows in by_segment.items()},
        "interval_80": {
            "coverage_pct": round(100 * sum(covered) / len(covered), 1),
            "by_segment_pct": {seg: round(100 * sum(r["lower"] <= r["actual"] <= r["upper"] for r in seg_rows) / len(seg_rows), 1)
                               for seg, seg_rows in by_segment.items()},
            "median_relative_width": round(float(np.median(width)), 3) if width else None,
        },
        "chosen_source": dict(sources),
        "seconds_per_forecast": {"median": round(seconds[len(seconds) // 2], 3), "max": round(seconds[-1], 3)},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=tuple(SPLITS), default="dev")
    parser.add_argument("--horizon", type=int, default=30)
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    rows = run(args.split, args.horizon)
    summary = summarize(rows)
    print(f"split={args.split} horizon={args.horizon}d windows={summary['windows']} sources={summary['chosen_source']}")
    header = f"{'':18s}" + "".join(f"{c:>18s}" for c in summary["overall"])
    print(header)
    for scope, table in [("overall", summary["overall"]), *summary["segments"].items()]:
        print(f"{scope:18s}" + "".join(f"{'WAPE ' + str(m['wape_pct']) + ' b' + str(m['bias_pct']):>18s}" for m in table.values()))
    print("80% interval coverage:", summary["interval_80"])
    print("seconds per forecast:", summary["seconds_per_forecast"])
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        payload = {"split": args.split, "horizon_days": args.horizon, "summary": summary}
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
