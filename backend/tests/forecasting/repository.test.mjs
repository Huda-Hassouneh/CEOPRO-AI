import assert from "node:assert/strict";
import { mock, test } from "node:test";
let allowed = true, exists = true, created, evidence, queries = [], transactionOptions;
const scope = { tenantId: "tenant", userId: "user", productId: "product" };
const target = new Date("2026-10-19");
const tx = {
  $queryRaw: async (parts, ...values) => { const sql = parts.join("?"); queries.push({ sql, values }); return sql.includes("priced_sales") ? [{ transaction_date: new Date().toISOString().slice(0,10), quantity: 0n, unit_price: 8, invalid_records: 0n }] : []; },
  products: { findMany: async (args) => { assert.equal(args.where.tenant_id, "tenant"); assert.equal(args.where.deleted_at, null); return [{ product_id: "product", product_name: { en: "Tea" }, category: "Tea" }]; }, findFirst: async (args) => { assert.deepEqual(args.where, { tenant_id: "tenant", product_id: "product", deleted_at: null }); return exists ? { product_id: "product", product_name: { en: "Tea" }, currency: "JOD", current_price: 8, category: "Tea" } : null; } },
  inventory: { findMany: async (args) => { assert.equal(args.where.tenant_id, "tenant"); assert.equal(args.where.product_id, "product"); if (args.select) assert.equal(args.select.warehouse_location, true); return [{ stock_quantity: 0, safety_stock: 0, updated_at: new Date(), warehouse_location: "Main" }]; } },
  demand_forecasts: { findMany: async (args) => { assert.equal(args.where.tenant_id, "tenant"); assert.equal(args.where.product_id, "product"); return []; }, create: async (args) => { created = args.data; return { forecast_id: "forecast" }; } },
  evidence_records: { create: async (args) => { evidence = args.data; return { evidence_id: "evidence" }; } }
};
await mock.module("../../src/config/database.ts", { namedExports: { prisma: { $transaction: async (callback, options) => { transactionOptions = options; return callback(tx); } } } });
await mock.module("../../src/modules/features/repo/usage.repo.ts", { namedExports: {
  getFeatureAccessInfo: async (tenant, feature, client) => { assert.equal(tenant, "tenant"); assert.equal(feature, "demand_prediction"); assert.equal(client, tx); return { subscription: {}, planFeature: allowed ? {} : null }; }
} });
const { persistGeneratedForecast, loadForecastGenerationInput, loadForecastData } = await import("../../src/modules/forecasting/repo/forecasting.repo.ts");
const { isForecastTransactionStartTimeout } = await import("../../src/modules/forecasting/repo/forecasting.transactions.ts");
const input = { ...scope, forecastStartDate: target, forecastEndDate: target, forecastTargetDate: target,
  expectedDemand: 0, rawExpectedDemand: 0.25, source: "baseline", confidenceScore: null, transactionsUsed: 1,
  lowerBound: null, upperBound: null, modelVersion: null, modelName: null,
  horizonDays: 7, modelHorizonDays: 7, priceCurrency: "JOD", dataSufficiency: { sufficient: false }, latestHistoryDate: "2026-10-12", historyDaysSupplied: 1 };
test("forecast and evidence persistence keeps tenant context, one-day meaning, zero and unavailable model metadata", async () => {
  const result = await persistGeneratedForecast(input);
  assert.deepEqual(transactionOptions, { maxWait: 10_000, timeout: 30_000 });
  assert.equal(result.forecastId, "forecast");
  assert.ok(queries[0].sql.includes("set_config")); assert.deepEqual(queries[0].values, ["tenant", "user"]);
  assert.equal(created.tenant_id, "tenant"); assert.equal(created.expected_demand, 0);
  assert.equal(created.forecast_start_date.getTime(), created.forecast_end_date.getTime());
  assert.equal(created.model_version, "UNSPECIFIED"); assert.equal(created.features_used.prediction_kind, "target_day");
  assert.equal(evidence.forecast_id, "forecast"); assert.equal(evidence.model_version, null);
  assert.equal(evidence.metric_value_json.raw_expected_demand, 0.25);
});
test("revoked entitlement or deleted product cannot receive a saved model result", async () => {
  created = null; allowed = false;
  await assert.rejects(persistGeneratedForecast(input), (error) => error.code === "FEATURE_NOT_INCLUDED");
  assert.equal(created, null);
  allowed = true; exists = false;
  assert.equal(await persistGeneratedForecast(input), null); assert.equal(created, null);
});
test("generation history uses tenant-scoped daily aggregates, recorded FX and bounded nonfuture records", async () => {
  exists = true; queries = [];
  const data = await loadForecastGenerationInput(scope);
  assert.deepEqual(transactionOptions, { maxWait: 10_000, timeout: 30_000, isolationLevel: "RepeatableRead" });
  assert.equal(data.currentStock, 0); assert.equal(data.priceCurrency, "JOD");
  assert.equal(data.transactions[0].quantity, 0); assert.equal(data.invalidRecords, 0);
  const source = queries.find((query) => query.sql.includes("priced_sales"));
  assert.ok(source.values.includes("tenant")); assert.ok(source.values.includes("product"));
  assert.equal(source.values.filter((value) => value === "JOD").length, 2);
  assert.match(source.sql, /converted_currency[\s\S]*exchange_rate > 0/);
  assert.match(source.sql, /transaction_date < /);
});
test("overview and post-generation detail reads retain tenant RLS and wait for a bounded transaction", async () => {
  for (const detail of [false, true]) {
    queries = [];
    const data = await loadForecastData("tenant", "user", new Date("2026-10-01"), target, "product", detail);
    assert.equal(data.products[0].product_id, "product");
    assert.deepEqual(transactionOptions, { maxWait: 10_000, timeout: 30_000, isolationLevel: "RepeatableRead" });
    assert.deepEqual(queries[0].values, ["tenant", "user"]);
  }
});
test("only transaction-start P2028 errors are treated as a temporary database wait", () => {
  assert.equal(isForecastTransactionStartTimeout({ code: "P2028", message: "Transaction API error: Unable to start a transaction in the given time." }), true);
  assert.equal(isForecastTransactionStartTimeout({ code: "P2028", meta: { error: "Unable to start a transaction in the given time." } }), true);
  for (const error of [null, "P2028", { code: "P2028", message: "Transaction already closed: expired transaction" }, { code: "P2002", message: "Unable to start a transaction in the given time." }, new Error("Unable to start a transaction in the given time.")]) {
    assert.equal(isForecastTransactionStartTimeout(error), false);
  }
});
