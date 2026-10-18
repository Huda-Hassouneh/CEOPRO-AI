import assert from "node:assert/strict";
import { mock, test } from "node:test";

const now = new Date();
const today = new Date(new Date(`${now.toISOString().slice(0, 10)}T00:00:00Z`).getTime() + 86_400_000);
const ago = (days) => new Date(now.getTime() - days * 86_400_000);
const add = (days) => new Date(today.getTime() + days * 86_400_000);
const tenant = "00000000-0000-4000-8000-000000000001";
const user = "00000000-0000-4000-8000-000000000002";
const products = [
  { product_id: "first", product_name: "First", category: "A", currency: "JOD", current_price: 10 },
  { product_id: "second", product_name: "Second", category: "B", currency: "JOD", current_price: 10 }
];
const observations = [
  { currency: "USD", scraped_price: 999, observed_at: ago(1) },
  { currency: "JOD", scraped_price: 10, observed_at: ago(2) },
  { currency: "JOD", scraped_price: 12, observed_at: ago(3) }
];
const mapping = {
  mapping_id: "mapping", global_competitor_id: "competitor",
  tenant_competitors: { product_match_rate: 0.8, custom_alias: null, global_competitors: { competitor_name: "Competitor" } }
};
let calls = [];
let transactionOptions;
let incomplete = false;
const db = {
  products: { findMany: async () => products },
  $queryRaw: async (parts, ...values) => {
    calls.push({ sql: parts.join("?"), values });
    return parts.join("").includes("competitor_score_snapshots")
      ? [{ global_competitor_id: "competitor", composite_score: 80, relevance_score: 80, market_activity_score: 50, calculated_at: ago(100) }] : [];
  },
  competitor_product_mappings: { findMany: async (query) => {
    calls.push({ query });
    if (query.include) {
      assert.equal(query.include.competitor_prices.where.currency, "JOD");
      assert.deepEqual(query.include.competitor_prices.where.scraped_price, { gt: 0 });
      return [{ ...mapping, competitor_prices: observations.filter((row) => row.currency === "JOD") }];
    }
    assert.deepEqual(query.select.competitor_prices.distinct, ["currency"]);
    return [{ product_id: "first", competitor_prices: observations.slice(0, 2) }];
  } },
  demand_forecasts: { findMany: async () => products.map((product, index) => ({
    product_id: product.product_id, forecast_id: `f-${index}`, expected_demand: index ? 50 : 100,
    forecast_start_date: today, forecast_end_date: add(incomplete ? 5 : 29), forecast_target_date: add(29),
    created_at: ago(1), model_version: "test", confidence_range_lower: null, confidence_range_upper: null
  })) },
  reviews: { findMany: async () => [] },
  transactions: { findMany: async () => [] },
  market_events: { findMany: async () => [] }
};
await mock.module("../../src/config/database.ts", { namedExports: { prisma: {
  $transaction: async (callback, options) => { transactionOptions = options; return callback(db); }
} } });
const { getMarketIntelligence } = await import("../../src/modules/market-intelligence/repo/market-int.repo.ts");
delete process.env.MARKET_INTELLIGENCE_MAX_SOURCE_AGE_DAYS;

test("overview sets RLS context before queries and uses comparable prices/complete segment horizons", async () => {
  calls = [];
  const result = await getMarketIntelligence(tenant, user, "first", 30);
  assert.match(calls[0].sql, /app.current_tenant_id/);
  assert.match(calls[0].sql, /app.current_user_id/);
  assert.deepEqual(calls[0].values, [tenant, user]);
  assert.equal(transactionOptions.isolationLevel, "RepeatableRead");
  assert.equal(result.metrics.find((row) => row.id === "averagePriceScore").value, 10);
  assert.equal(result.metrics.find((row) => row.id === "averageCompositeScore").value, 80);
  assert.equal(result.metrics.find((row) => row.id === "topSegmentScore").value, 10);
  assert.equal(result.competitors[0].freshness.score.status, "not_assessed");
  assert.equal(result.competitors[0].scoreCalculatedAt, ago(100).toISOString());
  assert.equal(result.pricingRecommendations[0].currency, "JOD");
});

test("partial forecast coverage does not contribute to the Top Segment demand component", async () => {
  incomplete = true;
  const result = await getMarketIntelligence(tenant, user, "first", 30);
  const segment = result.metrics.find((row) => row.id === "topSegmentScore");
  assert.equal(segment.components.demand, null);
  assert.equal(segment.components.pricing, 10);
  assert.equal(segment.forecastCoverage.completeProducts, 0);
  assert.equal(segment.dataStatus, "partial");
  incomplete = false;
});

test("configured freshness excludes an old snapshot and retains its provenance", async () => {
  process.env.MARKET_INTELLIGENCE_MAX_SOURCE_AGE_DAYS = "7";
  try {
    const result = await getMarketIntelligence(tenant, user, "first", 30);
    assert.equal(result.competitors[0].compositeScore, null);
    assert.equal(result.competitors[0].freshness.score.status, "stale");
    assert.equal(result.sectionStatuses.competitors, "partial");
    assert.equal(result.competitors[0].priceObservedAt, ago(2).toISOString());
  } finally { delete process.env.MARKET_INTELLIGENCE_MAX_SOURCE_AGE_DAYS; }
});
