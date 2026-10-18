# Forecasting Historical Backtesting

The backtesting pipeline measures whether XGBoost improves on simple forecasting methods before it
is trusted. It uses an expanding-window, one-step rolling-origin design:

```text
fold 1: train [past................] -> test [next day]
fold 2: train [past + observed day 1] -> test [next day]
fold 3: train [past + observed days 1-2] -> test [next day]
```

A test date is never included in its own training window. After that date would have become known in
real life, it may become history for the following fold. This simulates repeated daily forecasting
without random time-series shuffling or future leakage.

## Candidates

- `model`: `XGBoostDemandForecaster`
- `naive`: repeats the most recent demand
- `seasonal_naive`: repeats the previous seven-day pattern
- `moving_average`: repeats the trailing seven-day mean
- `previous_period`: reuses the immediately previous evaluation-length period (one day per fold)

## Metrics

- **MAE**: average absolute unit error; easy to explain operationally.
- **RMSE**: like MAE but penalizes large misses more strongly.
- **MAPE**: average percentage error on non-zero-demand dates. Zero-demand dates are explicitly
  excluded because percentage error is undefined when actual demand is zero.
- **MASE**: model MAE scaled by a naive in-sample error. Below 1 means better than that naive scale.

The winner is ranked by MAE, with RMSE as the deterministic tie-breaker. The report also records the
best baseline and the model's percentage MAE improvement over it.

## Run with deterministic demonstration data

```bash
python scripts/evaluate_forecasting.py \
  --demo-days 180 \
  --min-train-rows 60 \
  --max-folds 30 \
  --output-dir data/forecasting/evaluation
```

The demonstration series is deterministic (`--seed 42` by default), so repeated runs produce the
same comparison.

## Run with historical product data

Supply a daily, gap-free CSV:

```csv
date,quantity,avg_unit_price
2025-01-01,12,20.0
2025-01-02,15,20.0
```

Then run:

```bash
python scripts/evaluate_forecasting.py \
  --input-csv product_daily_history.csv \
  --output-dir data/forecasting/product-123
```

Outputs:

- `summary.json`: complete machine-readable configuration, metrics, ranking, and fold records.
- `predictions.csv`: one row per unseen test date with actual and every candidate prediction.
- `comparison.md`: supervisor-friendly metric table.

The script fails clearly for missing columns, duplicate/gapped dates, negative demand, invalid
configuration, or insufficient history. It never silently changes time order or fills missing demand
because those data-quality decisions belong in the ingestion layer.
