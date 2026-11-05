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

## Production-path backtest (horizon totals, by segment)

`scripts/evaluate_forecast_pipeline.py` scores what customers receive — `pipeline.choose_forecast`
(baseline/XGBoost selection, outlier capping, intermittent handling) and the stored range from
`pipeline.forecast_interval` — on the **total** demand over the horizon at three non-overlapping
rolling origins per series. Data is **synthetic** (seeded Poisson series in seven documented segments);
no real customer history exists in this repository, so these figures are not a claim about any
customer's accuracy. Seeds 0-5 (`--split dev`) were used to diagnose; seeds 100-111 (`--split test`,
252 windows) are reported below and were not used to choose any setting.

30-day totals, test split (WAPE % / bias %; lower WAPE is better, bias > 0 is over-forecast):

| Segment | pipeline | naive | seasonal_naive | moving_average_28 | ses | holt_damped |
|---|---|---|---|---|---|---|
| overall | 10.53 / -3.92 | 38.71 / 9.96 | 14.15 / -4.39 | 13.88 / -0.25 | 15.58 / -2.13 | 16.87 / -2.42 |
| stable | 3.85 / 0.19 | 20.12 / -0.87 | 6.76 / -0.09 | 3.89 / 0.03 | 6.48 / -0.84 | 6.46 / 0.76 |
| weekly_seasonal | 4.43 / -0.65 | 25.98 / 6.15 | 7.3 / 1.03 | 4.54 / -0.32 | 6.33 / -0.73 | 6.63 / -0.56 |
| trend_up | 7.75 / -7.2 | 20.4 / 2.32 | 6.93 / -2.3 | 6.91 / -5.81 | 6.59 / -2.78 | 5.55 / -2.7 |
| trend_down | 14.07 / 13.68 | 28.18 / 9.87 | 10.96 / 5.95 | 12.61 / 11.78 | 11.3 / 6.29 | 8.99 / 4.36 |
| promo_spikes | 3.93 / -1.5 | 20.32 / -7.67 | 11.14 / -10.35 | 5.41 / -4.09 | 10.9 / -10.28 | 13.1 / -12.76 |
| intermittent | 45.22 / -0.69 | 186.15 / 47.03 | 66.92 / 4.52 | 51.03 / -0.83 | 66.28 / 9.62 | 64.2 / 5.45 |
| with_outliers | 28.78 / -17.9 | 105.74 / 49.6 | 37.01 / -13.4 | 46.8 / 4.61 | 46.53 / 1.23 | 53.25 / 2.16 |

Pipeline overall: MAE 55.995, RMSE 163.409, MAPE 15.27%, MASE 1.079 (mean of per-window ratios to the
seasonal-naive horizon-total error on each series' own history; it exceeds 1 because quiet series with tiny denominators dominate the mean — WAPE is the fairer aggregate). Declining products (`trend_down`) are over-forecast by ~14%: the flat recent blend lags a decline, and seasonal-naive and damped-trend smoothing beat it there. That is an open overstock risk, not fixed here.

**80% range coverage** (share of windows whose actual total fell inside the stored range):

| | Before (one-day error × √h) | After (widened to past horizon-total misses) |
|---|---|---|
| 30-day, all segments | 55.6% | 79.0% |
| 30-day, stable | 80.6% | 83.3% |
| 30-day, weekly_seasonal | 77.8% | 91.7% |
| 30-day, trend_up | 27.8% | 72.2% |
| 30-day, trend_down | 25.0% | 80.6% |
| 30-day, promo_spikes | 66.7% | 77.8% |
| 30-day, intermittent | 58.3% | 69.4% |
| 30-day, with_outliers | 52.8% | 77.8% |
| 7-day, all segments | — | 77.0% |

Median range width rose from 0.142 to 0.23 of the actual total: the old range was
narrower than the evidence supported. Point forecasts are unchanged by this fix.

Known limits: 7-day windows in `promo_spikes` all start on a promotion day (the test origins align
with the synthetic 30-day promotion cycle), so 7-day coverage there is 16.7% — no history-only model
can foresee an unannounced promotion; a promotions calendar input would be needed. `with_outliers`
windows include bulk orders in the *actual* totals, which no forecast should predict. XGBoost was
chosen in 12 of 252 windows; the baseline guard rejected it elsewhere.
