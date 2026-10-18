import assert from "node:assert/strict";
import { test } from "node:test";
import { historyIsUsable, inventoryContext, sourceFreshness, usableForecasts } from "../../src/modules/forecasting/service/forecasting.policy.js";
import { forecastWindow, summarizeForecasts, type ForecastRow } from "../../src/modules/forecasting/service/forecasting.calculations.js";
const now = new Date("2026-10-12T12:00:00Z");
const row: ForecastRow = { forecast_id: "f", forecast_start_date: new Date("2026-10-13"), forecast_end_date: new Date("2026-10-19"),
  forecast_target_date: new Date("2026-10-19"), expected_demand: 20, confidence_range_lower: null, confidence_range_upper: null,
  created_at: new Date("2026-10-11"), model_version: "baseline" };
test("previous Node target-day rows cannot masquerade as a seven-day total", () => {
  const legacy = { ...row, features_used: { source: "baseline", horizon_days: 7, transactions_used: 6, data_sufficiency: {} } };
  assert.equal(forecastWindow(legacy)!.start.toISOString(), row.forecast_target_date!.toISOString());
  assert.equal(summarizeForecasts([legacy], new Date("2026-10-13"), 7, now).expectedDemand, null);
  assert.equal(summarizeForecasts([row], new Date("2026-10-13"), 7, now).expectedDemand, 20);
});
test("history requires valid, unique, nonfuture days and nonnegative numeric sales", () => {
  const sale = { transaction_date: "2026-10-11", quantity: 0, unit_price: 0 };
  assert.equal(historyIsUsable([sale], now), true);
  assert.equal(historyIsUsable([sale, sale], now), false);
  assert.equal(historyIsUsable([{ ...sale, transaction_date: "2026-10-13" }], now), false);
});
test("stored integer rounding cannot erase fractional model demand or invalidate its real bounds", () => {
  const values = Array.from({ length: 7 }, (_, offset) => ({ ...row, forecast_id: `raw-${offset}`,
    forecast_start_date: null, forecast_end_date: null, forecast_target_date: new Date(new Date("2026-10-13").getTime() + offset * 86400000),
    expected_demand: 0, confidence_range_lower: 0.1, confidence_range_upper: 0.9,
    features_used: { prediction_kind: "target_day", raw_expected_demand: 0.25 } }));
  assert.equal(summarizeForecasts(values, new Date("2026-10-13"), 7, now).expectedDemand, 1.75);
  for (const raw_expected_demand of [-1, "bad", Infinity]) {
    const bad = values.map((value, index) => index ? value : { ...value, features_used: { prediction_kind: "target_day", raw_expected_demand } });
    assert.equal(summarizeForecasts(bad, new Date("2026-10-13"), 7, now).expectedDemand, null);
  }
});
test("freshness has no invented cutoff; configured stale forecasts and inventory are unavailable", () => {
  const previous = process.env.FORECASTING_MAX_SOURCE_AGE_DAYS;
  try {
    delete process.env.FORECASTING_MAX_SOURCE_AGE_DAYS;
    assert.equal(sourceFreshness(new Date("2020-01-01"), now).status, "not_assessed");
    process.env.FORECASTING_MAX_SOURCE_AGE_DAYS = "1";
    assert.equal(usableForecasts([row], now).length, 0);
    assert.equal(inventoryContext([{ stock_quantity: 20, updated_at: new Date("2020-01-01") }], now).currentStock, null);
  } finally { if (previous === undefined) delete process.env.FORECASTING_MAX_SOURCE_AGE_DAYS; else process.env.FORECASTING_MAX_SOURCE_AGE_DAYS = previous; }
});
test("warehouse stock preserves zero and missing/negative safety stock stays unknown", () => {
  const stock = inventoryContext([{ stock_quantity: 0, safety_stock: 1 }, { stock_quantity: 2, safety_stock: 3 }], now);
  assert.equal(stock.currentStock, 2); assert.equal(stock.safetyStock, 4);
  assert.equal(inventoryContext([{ stock_quantity: 0 }], now).currentStock, 0);
  assert.equal(inventoryContext([{ stock_quantity: -1 }], now).currentStock, null);
});
