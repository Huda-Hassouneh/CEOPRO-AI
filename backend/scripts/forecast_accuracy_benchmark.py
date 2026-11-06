"""Demand-forecast accuracy benchmark on the seven demo companies.

Runs the production model selection (``pipeline.choose_forecast``) at several
past forecast origins for every product of every demo company and compares
each 30-day forecast TOTAL (the figure every screen, the restock advice and
the assistant use) with what was actually sold.

Because the demo generator knows each product's true expected demand for every
day, the report also gives an **oracle ceiling**: the accuracy of forecasting
the exact true mean (the generator's demand driver, rescaled by each product's
constant ratio of recorded to expected quantity). The gap between the oracle and the actual sales is pure
randomness that no model can remove, so a target above the oracle is not
reachable on this data.

Accuracy definitions (both reported, per segment):

- ``accuracy_wape``: 1 - sum|forecast - actual| / sum(actual). Volume-weighted;
  the usual business "forecast accuracy" figure.
- ``accuracy_median_product``: 100% minus the median per-product absolute
  percentage error.

Products are segmented by average daily units over the 90 days before the
origin: ``fast`` (>= 5/day), ``medium`` (1-5/day) and ``slow`` (< 1/day).

Usage (no database or network needed)::

    cd backend && python -m scripts.forecast_accuracy_benchmark [--origins 6] [--only zaytouna] [--report out.json]
"""

import argparse
import json
import os
import random
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.demo_companies.generate import active, expected_units, generate_sales  # noqa: E402
from scripts.demo_companies.profiles import COMPANIES  # noqa: E402
from src.ai.core.calendar import weekend_days  # noqa: E402
from src.ai.forecasting import cold_start  # noqa: E402
from src.ai.forecasting.pipeline import cap_isolated_outliers, choose_forecast  # noqa: E402

HORIZON = 30
DEFAULT_END = date(2026, 10, 28)


def _segment(rate: float) -> str:
    return "fast" if rate >= 5 else "medium" if rate >= 1 else "slow"


def company_series(company, end: date) -> dict:
    """{product_name: DataFrame[date, quantity, avg_unit_price, expected]} - the
    same daily shape data_access.load_daily_demand() builds from invoices."""
    index = list(COMPANIES).index(company)
    lines = generate_sales(company, end, random.Random(2026_10_06 + index))
    qty, price = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(list))
    for line in lines:
        name = line["product"].name_en
        qty[name][line["date"]] += float(line["qty"])
        price[name][line["date"]].append(float(line["price"]))
    series = {}
    for product in company.products:
        name = product.name_en
        if not qty.get(name):
            continue
        first = min(qty[name])
        days = pd.date_range(first, end, freq="D")
        frame = pd.DataFrame({
            "date": days,
            "quantity": [qty[name].get(d.date(), 0.0) for d in days],
            "avg_unit_price": [np.mean(price[name][d.date()]) if price[name].get(d.date()) else np.nan for d in days],
            "expected": [expected_units(company, product, d.date()) if active(product, d.date()) else 0.0 for d in days],
        })
        frame["avg_unit_price"] = frame["avg_unit_price"].ffill().bfill()
        series[name] = frame
    return series


def _company_rows(key: str, origins: int, end: date) -> list:
    company = next(c for c in COMPANIES if c.key == key)
    weekend = weekend_days(company.country)
    rows = []
    for name, frame in company_series(company, end).items():
        for k in range(1, origins + 1):
            cut = len(frame) - k * HORIZON
            if cut < 60:
                continue
            history = frame.iloc[:cut][["date", "quantity", "avg_unit_price"]].reset_index(drop=True)
            future = frame.iloc[cut:cut + HORIZON]
            # expected_units() is the generator's demand driver, not recorded quantity (kg lines, B2B order
            # sizes and per-receipt de-duplication change the scale), so the oracle is that driver rescaled
            # by the product's own constant ratio of recorded to expected quantity.
            scale = float(frame["quantity"].sum()) / max(float(frame["expected"].sum()), 1e-9)
            capped, _ = cap_isolated_outliers(history)
            price = float(history["avg_unit_price"].iloc[-1])
            choice = choose_forecast(capped, cold_start.assess(capped), price, None, weekend, HORIZON)
            rows.append({
                "company": company.key, "product": name, "origin": history["date"].iloc[-1].date().isoformat(),
                "segment": _segment(float(history["quantity"].tail(90).mean())),
                "actual": float(future["quantity"].sum()), "forecast": float(np.sum(choice["values"])),
                "oracle": float(future["expected"].sum()) * scale, "method": choice["name"],
            })
    return rows


def _one_thread_per_worker():
    """XGBoost uses every core by default; several worker processes each doing so oversubscribe the CPU
    and run many times slower than one process (seen: >2 h instead of 20 min on 4 cores)."""
    from src.ai.forecasting import model
    model.DEFAULT_PARAMS["n_jobs"] = 1


def run(origins: int, only=None, end: date = DEFAULT_END, workers: int = 1) -> dict:
    started = time.time()
    keys = [c.key for c in COMPANIES if not only or c.key in only]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers, initializer=_one_thread_per_worker) as pool:
            parts = list(pool.map(_company_rows, keys, [origins] * len(keys), [end] * len(keys)))
    else:
        parts = [_company_rows(key, origins, end) for key in keys]
    return {"rows": [row for part in parts for row in part], "seconds": round(time.time() - started, 1)}


def summarize(rows: list) -> dict:
    def stats(subset):
        actual = np.array([r["actual"] for r in subset])
        out = {"n": len(subset)}
        if not len(subset) or actual.sum() == 0:
            return out
        for key in ("forecast", "oracle"):
            predicted = np.array([r[key] for r in subset])
            nonzero = actual > 0
            ape = np.abs(predicted[nonzero] - actual[nonzero]) / actual[nonzero]
            out[key] = {
                "accuracy_wape": round(100 * (1 - np.abs(predicted - actual).sum() / actual.sum()), 2),
                "accuracy_median_product": round(100 * (1 - float(np.median(ape))), 2),
                "share_within_5pct": round(100 * float(np.mean(ape <= 0.05)), 1),
            }
        return out

    report = {"overall": stats(rows)}
    for segment in ("fast", "medium", "slow"):
        report[segment] = stats([r for r in rows if r["segment"] == segment])
    report["by_company"] = {c: stats([r for r in rows if r["company"] == c]) for c in sorted({r["company"] for r in rows})}
    # Company-level totals (all products summed per origin) - the figure an
    # owner sees for the whole business.
    totals = defaultdict(lambda: {"actual": 0.0, "forecast": 0.0, "oracle": 0.0})
    for r in rows:
        key = (r["company"], r["origin"])
        for f in ("actual", "forecast", "oracle"):
            totals[key][f] += r[f]
    report["company_totals"] = stats([{**v, "segment": "all"} for v in totals.values()])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--origins", type=int, default=6, help="past 30-day windows per product (default 6)")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--workers", type=int, default=min(7, os.cpu_count() or 1))
    parser.add_argument("--report")
    args = parser.parse_args()
    result = run(args.origins, set(args.only) if args.only else None, workers=args.workers)
    summary = summarize(result["rows"])
    print(json.dumps(summary, indent=1))
    print(f"{len(result['rows'])} forecasts in {result['seconds']}s")
    if args.report:
        Path(args.report).write_text(json.dumps({"summary": summary, **result}, indent=1))


if __name__ == "__main__":
    main()
