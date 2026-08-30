# Forecast Backtest Comparison

- Method: expanding-window one-step rolling-origin backtest
- Evaluation period: 2025-05-31T00:00:00 to 2025-06-29T00:00:00
- Folds: 30
- Winner by MAE: **model**
- Best baseline: **seasonal_naive**
- Model MAE improvement over best baseline: **40.64%**

| Candidate | MAE | RMSE | MAPE (%) | MASE |
|---|---:|---:|---:|---:|
| model | 1.1924 | 1.4615 | 6.6129 | 0.3833 |
| seasonal_naive | 2.0088 | 2.7290 | 10.6210 | 0.6457 |
| naive | 3.0743 | 4.4742 | 18.4379 | 0.9882 |
| previous_period | 3.0743 | 4.4742 | 18.4379 | 0.9882 |
| moving_average | 3.6269 | 4.1902 | 20.3139 | 1.1659 |
