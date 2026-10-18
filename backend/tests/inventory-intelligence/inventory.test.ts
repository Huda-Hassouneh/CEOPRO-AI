import assert from "node:assert/strict";
import { test } from "node:test";
import { inventoryContext } from "../../src/modules/forecasting/service/forecasting.policy.js";
import { supportedInventoryRecommendation } from "../../src/modules/forecasting/service/inventory-recommendation.js";
import { summarizeInventory } from "../../src/modules/dashboard/helper/dashboard.helpers.js";

const now = new Date("2026-10-13T12:00:00Z");
const stock = (quantity = 0, safety: unknown = 2) => inventoryContext([
  { stock_quantity: quantity, safety_stock: safety, updated_at: new Date("2026-10-12"), warehouse_location: "Main" }
], now);
const forecast = () => ({ forecast_id: "f", forecast_start_date: new Date("2026-10-14"), forecast_end_date: new Date("2026-10-20"),
  forecast_target_date: new Date("2026-10-20"), expected_demand: 10, confidence_range_lower: null, confidence_range_upper: null,
  created_at: new Date("2026-10-12T12:00:00Z"), model_version: "baseline", features_used: { confidence_score: 0.2 },
  recommendation_outcomes: [{ recommendation_id: "r", forecast_id: "f", recommended_action: "RESTOCK_NOW", created_at: now }] });
test("zero stock supports a saved restock decision and never substitutes confidence for accuracy", () => {
  const result = supportedInventoryRecommendation([forecast()], stock(), "complete", 10, now);
  assert.equal(result.recommendation?.suggestedQuantity, 12);
  assert.equal(result.recommendation?.action, "restock");
  assert.equal(result.recommendation?.confidenceScore, 0.2);
  assert.equal(result.recommendation?.modelAccuracy, null);
  assert.equal(result.recommendation?.calculation?.currentStock, 0);
});
test("warehouse totals use every valid balance and report the oldest source date", () => {
  const context = inventoryContext([
    { stock_quantity: 2, safety_stock: 1, updated_at: new Date("2026-10-12"), warehouse_location: "East" },
    { stock_quantity: 3, safety_stock: 2, updated_at: new Date("2026-10-11"), warehouse_location: "West" }
  ], now);
  assert.equal(context.currentStock, 5); assert.equal(context.safetyStock, 3);
  assert.equal(context.freshness.timestamp, "2026-10-11T00:00:00.000Z");
  assert.equal(context.latestUpdatedAt, "2026-10-12T00:00:00.000Z");
});
test("duplicate warehouses, invalid quantities and a future date cannot produce stock totals", () => {
  const row = { stock_quantity: 2, updated_at: new Date("2026-10-12"), warehouse_location: " Main " };
  assert.equal(inventoryContext([row, { ...row, warehouse_location: "main" }], now).reason, "DUPLICATE_WAREHOUSE");
  assert.equal(inventoryContext([row, { ...row, warehouse_location: "West", updated_at: new Date("2026-10-14") }], now).reason, "INVALID_STOCK_DATE");
  for (const stock_quantity of [-1, NaN, 0.5, Number.MAX_SAFE_INTEGER + 1]) assert.equal(inventoryContext([{ ...row, stock_quantity }], now).currentStock, null);
});
test("partial, undated, missing and changed inputs suppress saved actions with an explicit reason", () => {
  const run = (context = stock(), coverage = "complete", rows = [forecast()]) => supportedInventoryRecommendation(rows, context, coverage, 10, now);
  assert.equal(run(inventoryContext([], now)).status.reason, "MISSING_INVENTORY");
  assert.equal(run(inventoryContext([{ stock_quantity: 0 }], now)).status.reason, "UNDATED_INVENTORY");
  assert.equal(run(stock(), "partial").status.reason, "INCOMPLETE_FORECAST");
  const old = forecast(); old.recommendation_outcomes[0]!.created_at = new Date("2026-10-11");
  assert.equal(run(stock(), "complete", [old]).status.reason, "OUTDATED_RECOMMENDATION");
  const changed = inventoryContext([{ stock_quantity: 2, safety_stock: 1, updated_at: now }], now);
  old.recommendation_outcomes[0]!.created_at = new Date("2026-10-12T14:00:00Z");
  assert.equal(run(changed, "complete", [old]).status.reason, "STOCK_CHANGED");
  assert.equal(run(stock(100)).status.reason, "INCONSISTENT_RECOMMENDATION");
  assert.equal(run(stock(0, null)).status.reason, "MISSING_SAFETY_STOCK");
  assert.equal(run(stock(), "complete", []).status.reason, "NO_HORIZON_RECOMMENDATION");
});
test("a combined daily horizon cannot borrow a daily action; fractional estimates round up once", () => {
  const duplicate = { ...forecast(), forecast_id: "daily" };
  assert.equal(supportedInventoryRecommendation([forecast(), duplicate], stock(), "complete", 10, now).status.reason, "NO_HORIZON_RECOMMENDATION");
  assert.equal(supportedInventoryRecommendation([forecast()], stock(), "complete", 10.25, now).recommendation?.suggestedQuantity, 13);
  const other = forecast(); other.recommendation_outcomes[0]!.forecast_id = "other";
  assert.equal(supportedInventoryRecommendation([other], stock(), "complete", 10, now).status.reason, "INVALID_RECOMMENDATION");
});
test("dashboard excludes unusable products and never hides a zero-stock product", () => {
  const row = { inventory_id: "a", product_id: "p", stock_quantity: 0, reorder_level: 2,
    updated_at: new Date("2026-10-12"), warehouse_location: "Main", products: { product_name: { en: "Tea" } } };
  const result = summarizeInventory([row, { ...row, inventory_id: "b", product_id: "invalid", stock_quantity: -1 }], now);
  assert.equal(result.outOfStock, 1); assert.equal(result.totalItems, 1); assert.equal(result.excludedProducts, 1);
  assert.equal(result.healthPercent, 0); assert.equal(result.items[0]?.quantity, 0);
  assert.equal(summarizeInventory([row, { ...row, inventory_id: "b" }], now).healthPercent, null);
});
test("configured stale inventory is rejected without inventing an age policy", () => {
  const previous = process.env.FORECASTING_MAX_SOURCE_AGE_DAYS;
  try {
    delete process.env.FORECASTING_MAX_SOURCE_AGE_DAYS;
    const old = [{ stock_quantity: 1, safety_stock: 1, updated_at: new Date("2026-01-01") }];
    assert.equal(inventoryContext(old, now).currentStock, 1);
    process.env.FORECASTING_MAX_SOURCE_AGE_DAYS = "3";
    assert.equal(inventoryContext(old, now).reason, "STALE_INVENTORY");
    assert.equal(supportedInventoryRecommendation([forecast()], inventoryContext(old, now), "complete", 10, now).recommendation, null);
  } finally { if (previous === undefined) delete process.env.FORECASTING_MAX_SOURCE_AGE_DAYS; else process.env.FORECASTING_MAX_SOURCE_AGE_DAYS = previous; }
});
