import assert from "node:assert/strict";
import { mock, test } from "node:test";
let allowed = true, snapshot;
const now = new Date(); const day = new Date(`${now.toISOString().slice(0, 10)}T00:00:00Z`);
const tomorrow = new Date(day.getTime() + 86400000); const end = new Date(day.getTime() + 7 * 86400000);
const earlier = new Date(now.getTime() - 60000);
function reset() {
  allowed = true;
  snapshot = { products: [{ product_id: "product", product_name: { en: "Tea" }, category: {}, currency: "JOD" }],
    inventory: [{ product_id: "product", stock_quantity: 0, safety_stock: 1, updated_at: earlier, warehouse_location: "Main" }], history: [], modelVersions: [],
    forecasts: [{ forecast_id: "forecast", product_id: "product", expected_demand: 10, forecast_start_date: tomorrow, forecast_end_date: end, forecast_target_date: end,
      created_at: earlier, confidence_range_lower: null, confidence_range_upper: null, model_version: "baseline", features_used: { confidence_score: 0.2 },
      recommendation_outcomes: [{ recommendation_id: "recommendation", forecast_id: "forecast", recommended_action: "restock", created_at: earlier }] }] };
}
await mock.module("../../src/modules/features/repo/usage.repo.ts", { namedExports: {
  getFeatureAccessInfo: async (tenant, code) => { assert.equal(tenant, "tenant"); assert.equal(code, "inventory_intelligence"); return { subscription: {}, planFeature: allowed ? {} : null }; }
} });
await mock.module("../../src/modules/forecasting/repo/forecasting.repo.ts", { namedExports: {
  loadForecastData: async (tenant, user, start, finish, product) => { assert.equal(tenant, "tenant"); assert.equal(user, "user"); assert.equal(product, "product"); return snapshot; },
  loadForecastGenerationInput: async () => { throw Error("No generation in inventory read"); },
  persistGeneratedForecast: async () => { throw Error("No new recommendation/forecast writes"); }
} });
const { getDemandDetail, getDemandOverview } = await import("../../src/modules/forecasting/service/forecasting.service.ts");
test("existing detail and overview expose a supported saved action for genuine zero stock", async () => {
  reset();
  const detail = await getDemandDetail("tenant", "product", "user", 7);
  assert.equal(detail.recommendation.suggestedQuantity, 11);
  assert.equal(detail.recommendation.confidenceScore, 0.2);
  const overview = await getDemandOverview("tenant", 7, "product", "user");
  assert.equal(overview.forecasts[0].recommendedAction, "restock");
});
test("denied inventory access hides action, quantity, and recommendation availability details", async () => {
  reset(); allowed = false;
  const detail = await getDemandDetail("tenant", "product", "user", 7);
  assert.equal(detail.recommendation, null); assert.equal(detail.recommendationStatus, null);
  const overview = await getDemandOverview("tenant", 7, "product", "user");
  assert.equal(overview.forecasts[0].recommendedAction, null); assert.equal(overview.forecasts[0].suggestedQuantity, null);
  assert.equal(overview.forecasts[0].recommendationStatus, null);
});
test("target-day forecasts and duplicate warehouse balances cannot yield a period recommendation", async () => {
  reset(); snapshot.forecasts[0].features_used.prediction_kind = "target_day";
  let detail = await getDemandDetail("tenant", "product", "user", 7);
  assert.equal(detail.recommendation, null); assert.equal(detail.recommendationStatus.reason, "INCOMPLETE_FORECAST");
  reset(); snapshot.inventory.push({ ...snapshot.inventory[0] });
  detail = await getDemandDetail("tenant", "product", "user", 7);
  assert.equal(detail.metrics.find((metric) => metric.id === "currentStock").value, null);
  assert.equal(detail.recommendationStatus.reason, "DUPLICATE_WAREHOUSE");
});
