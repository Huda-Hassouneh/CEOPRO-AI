# Demand Forecasting Tests

Covers both pure demand-forecast calculations and the service/controller/entitlement contract for the `demand_prediction` feature.

| File | What it tests |
| --- | --- |
| `forecasting.test.ts` | Seven-day totals/trends, preserving zero, latest revision selection, excluding future-created forecasts, unavailable/partial coverage semantics, period forecasts vs daily forecasts, overlap protection, confidence-range rules, invalid bounds/periods. |
| `forecasting-contract.test.ts` | Strict query validation; overview/detail consistency; tenant scoping; stock aggregation; missing accuracy/AI insight behavior; 400/404 controller responses; authenticated tenant + boolean entitlement route guard; entitlement middleware behavior; persisted restock quantity using forecast + all warehouse safety stock with zero clamp. |

The contract test replaces the Prisma transaction boundary with deterministic in-memory behavior; it is designed not to contact the configured database.
