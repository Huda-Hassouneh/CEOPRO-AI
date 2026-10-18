import assert from "node:assert/strict";
import { mock, test } from "node:test";
let allowed = true, product, provider, calls = [], saved = [], failProvider = false;
const today = new Date().toISOString().slice(0, 10);
const target = new Date(new Date(`${today}T00:00:00Z`).getTime() + 7 * 86400000).toISOString().slice(0, 10);
const input = { tenantId: "tenant", userId: "user", productId: "product", horizonDays: 7 };
const sale = { transaction_date: today, quantity: 4, unit_price: 8 };
const reset = () => {
  allowed = true; failProvider = false; calls = []; saved = [];
  product = { productId: "product", priceCurrency: "JOD", productName: "Tea", category: "Tea", currentPrice: 8, currentStock: 0,
    invalidRecords: 0, transactions: [sale] };
  provider = { product_name: "Tea", transactions_used: 1, result: { status: "OK", source: "baseline",
    expected_demand: 4.25, forecast_target_date: target, confidence_score: 0.2,
    data_sufficiency: { sufficient: false, available_days: 1, minimum_required: 28 } }, persisted_records: [] };
};
await mock.module("../../src/modules/features/repo/usage.repo.ts", { namedExports: {
  getFeatureAccessInfo: async () => ({ subscription: {}, planFeature: allowed ? {} : null })
} });
await mock.module("../../src/modules/forecasting/repo/forecasting.repo.ts", { namedExports: {
  loadForecastGenerationInput: async () => product,
  loadForecastData: async () => { throw new Error("unexpected read"); },
  persistGeneratedForecast: async (value) => { saved.push(value); return { forecastId: "forecast", evidenceId: "evidence" }; }
} });
await mock.module("../../src/modules/forecasting/client/forecasting.client.ts", { namedExports: {
  requestDemandForecast: async (value) => { calls.push(value); if (failProvider) throw new Error("provider failure"); return provider; },
  isForecastingClientError: () => false
} });
const { generateDemandForecast } = await import("../../src/modules/forecasting/service/forecasting.service.ts");

test("generation checks entitlement before accessing model or writing forecasts", async () => {
  reset(); allowed = false;
  await assert.rejects(generateDemandForecast(input), (error) => error.code === "FEATURE_NOT_INCLUDED");
  assert.equal(calls.length, 0); assert.equal(saved.length, 0);
});
test("missing, invalid and outdated history do not invent values or call AI", async () => {
  reset(); product.transactions = [];
  assert.equal((await generateDemandForecast(input)).reason, "NO_HISTORY");
  for (const bad of [{ ...sale, quantity: -1 }, { ...sale, transaction_date: "2026-02-30" }, { ...sale, unit_price: -1 }]) {
    product.transactions = [bad]; assert.equal((await generateDemandForecast(input)).reason, "INVALID_HISTORY");
  }
  product.transactions = [{ ...sale, transaction_date: "2020-01-01" }];
  assert.equal((await generateDemandForecast(input)).reason, "STALE_HISTORY");
  assert.equal(calls.length, 0); assert.equal(saved.length, 0);
});
test("target-day output is saved as one day, with genuine baseline provenance", async () => {
  reset(); const result = await generateDemandForecast(input);
  assert.equal(result.status, "OK"); assert.equal(result.expected_demand, 4.25);
  assert.equal(result.raw_expected_demand, 4.25); assert.equal(result.prediction_kind, "target_day");
  assert.equal(saved[0].forecastStartDate.getTime(), saved[0].forecastEndDate.getTime());
  assert.equal(saved[0].modelVersion, null); assert.equal(saved[0].lowerBound, null);
  assert.equal(saved[0].confidenceScore, 0.2); assert.equal(calls[0].currentStock, 0);
  assert.equal(calls[0].transactions[0].product_name, "Tea");
});
test("zero demand and real bounds/model version are preserved", async () => {
  reset(); Object.assign(provider.result, { expected_demand: 0, confidence_score: 0,
    confidence_range_lower: 0, confidence_range_upper: 2, model_version: "version-7", model_name: "Actual model" });
  const result = await generateDemandForecast(input);
  assert.equal(result.expected_demand, 0); assert.equal(result.confidence_score, 0);
  assert.equal(saved[0].modelVersion, "version-7"); assert.equal(saved[0].upperBound, 2);
});
test("a missing recent sales day extends model lookahead without fabricating input sales", async () => {
  reset(); product.transactions = [{ ...sale, transaction_date: new Date(new Date(`${today}T00:00:00Z`).getTime() - 86400000).toISOString().slice(0, 10) }];
  const result = await generateDemandForecast(input);
  assert.equal(result.forecast_target_date, target);
  assert.equal(calls[0].horizonDays, 8); assert.equal(calls[0].transactions.length, 1);
  assert.equal(saved[0].horizonDays, 7); assert.equal(saved[0].modelHorizonDays, 8);
});
test("model UNKNOWN saves no fabricated forecast and mismatched dates fail validation", async () => {
  reset(); provider.result = { status: "UNKNOWN" };
  const unknown = await generateDemandForecast(input);
  assert.equal(unknown.reason, "MODEL_UNAVAILABLE");
  assert.equal(unknown.transactions_used, provider.transactions_used);
  assert.equal(saved.length, 0);
  reset(); provider.result.forecast_target_date = today;
  await assert.rejects(generateDemandForecast(input), (error) => error.kind === "malformed_response");
  assert.equal(saved.length, 0);
});
test("concurrent duplicate generation in one process shares a call; failures allow an explicit retry", async () => {
  reset(); await Promise.all([generateDemandForecast(input), generateDemandForecast(input)]);
  assert.equal(calls.length, 1); assert.equal(saved.length, 1);
  reset(); failProvider = true; await assert.rejects(generateDemandForecast(input), /provider failure/);
  failProvider = false; await generateDemandForecast(input); assert.equal(saved.length, 1);
});
