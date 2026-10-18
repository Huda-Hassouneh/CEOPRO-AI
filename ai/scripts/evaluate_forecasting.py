"""Run reproducible historical demand backtesting and write JSON/CSV/Markdown reports."""

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import xgboost

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ai.forecasting.backtesting import (  # noqa: E402
    BacktestConfig, run_backtest, write_backtest_report,
)


def demo_history(days: int = 180, seed: int = 42) -> pd.DataFrame:
    if days < 60:
        raise ValueError("demo history requires at least 60 days")
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=days, freq="D")
    weekend = np.isin(dates.dayofweek, [4, 5])
    promotion = (np.arange(days) % 28) < 4
    price = np.where(promotion, 16.0, 20.0)
    trend = np.arange(days) * 0.025
    demand = 11.0 + trend + weekend * 7.0 + promotion * 5.0
    demand = np.clip(demand + rng.normal(0, 1.2, days), 0, None)
    return pd.DataFrame({
        "date": dates, "quantity": demand, "avg_unit_price": price,
    })


def load_history(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", help="CSV with date, quantity, avg_unit_price")
    parser.add_argument("--output-dir", default="data/forecasting/evaluation")
    parser.add_argument("--min-train-rows", type=int, default=60)
    parser.add_argument("--max-folds", type=int, default=30)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--demo-days", type=int, default=180)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--current-stock", type=float)
    args = parser.parse_args()

    daily = load_history(args.input_csv) if args.input_csv else demo_history(
        args.demo_days, args.seed
    )
    config = BacktestConfig(
        min_train_rows=args.min_train_rows,
        max_folds=args.max_folds,
        step=args.step,
    )
    result = run_backtest(daily, config, current_stock=args.current_stock)
    result["input"] = (
        {"type": "csv", "path": str(Path(args.input_csv).resolve())}
        if args.input_csv
        else {"type": "deterministic_demo", "days": args.demo_days, "seed": args.seed}
    )
    result["library_versions"] = {
        "numpy": np.__version__, "pandas": pd.__version__, "xgboost": xgboost.__version__,
    }
    paths = write_backtest_report(result, Path(args.output_dir))

    print(f"Backtest folds: {result['n_folds']}")
    print(f"Evaluation: {result['evaluation_start']} -> {result['evaluation_end']}")
    print("Candidate metrics:")
    for name in result["ranking_by_mae"]:
        metric = result["metrics"][name]
        print(
            f"  {name:18} MAE={metric['mae']:.4f} "
            f"RMSE={metric['rmse']:.4f} MAPE={metric['mape']:.2f}% "
            f"MASE={metric['mase']:.4f}"
        )
    print(f"Winner: {result['winner']}")
    print(f"Model beats all baselines: {result['model_beats_all_baselines']}")
    for label, path in paths.items():
        print(f"{label}: {path}")


if __name__ == "__main__":
    main()
