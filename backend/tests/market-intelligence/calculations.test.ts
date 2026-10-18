import assert from "node:assert/strict";
import { test } from "node:test";
import {
  aggregateMarketStatus, comparableMarketPrice, MarketProductNotFoundError,
  selectMarketProduct, sourceAgePolicy, sourceFreshness, summarizeMarketDemand
} from "../../src/modules/market-intelligence/service/market-int.calculations.js";
import { addDays, type ForecastRow } from "../../src/modules/forecasting/service/forecasting.calculations.js";
import { marketOverviewQuerySchema } from "../../src/modules/market-intelligence/types/market-int.validation.js";

const asOf = new Date("2026-10-12T16:00:00Z");
const start = new Date("2026-10-13T00:00:00Z");
const forecast = (offset: number, units: number, changes: Partial<ForecastRow> = {}) => ({
  product_id: "own-product", forecast_id: `f-${offset}`, expected_demand: units,
  forecast_target_date: addDays(start, offset), forecast_start_date: null,
  forecast_end_date: null, created_at: addDays(start, -1), model_version: "test",
  confidence_range_lower: null, confidence_range_upper: null, ...changes
});

test("explicit missing/foreign/deleted products are rejected, including an empty tenant", () => {
  assert.equal(selectMarketProduct([{ product_id: "own-product" }])?.product_id, "own-product");
  assert.equal(selectMarketProduct([]), null);
  for (const products of [[], [{ product_id: "own-product" }]]) {
    assert.throws(() => selectMarketProduct(products, "other-product"), MarketProductNotFoundError);
  }
});

test("query validation rejects malformed IDs, array parameters, and unsupported horizons", () => {
  for (const query of [{ productId: "garbage" }, { productId: ["id"] }, { periodDays: "7" }, { periodDays: "NaN" }]) {
    assert.equal(marketOverviewQuerySchema.safeParse(query).success, false);
  }
  assert.equal(marketOverviewQuerySchema.safeParse({ periodDays: "90" }).success, true);
  const id = "ABCDEF12-1234-4234-8234-123456789ABC";
  assert.equal(marketOverviewQuerySchema.parse({ productId: id }).productId, id.toLowerCase());
});

test("segment demand uses an exact horizon once even when daily forecasts also exist", () => {
  const daily = Array.from({ length: 30 }, (_, day) => forecast(day, 10));
  const exact = forecast(29, 400, { forecast_start_date: start, forecast_end_date: addDays(start, 29) });
  const result = summarizeMarketDemand([...daily, exact], ["own-product"], asOf, 30, null).get("own-product")!;
  assert.equal(result.status, "complete");
  assert.equal(result.expectedDemand, 400);
});

test("overlapping and partly intersecting windows cannot inflate segment demand", () => {
  const left = forecast(19, 200, { forecast_start_date: start, forecast_end_date: addDays(start, 19) });
  const right = forecast(29, 200, { forecast_start_date: addDays(start, 10), forecast_end_date: addDays(start, 29) });
  const wide = forecast(35, 999, { forecast_start_date: addDays(start, -5), forecast_end_date: addDays(start, 35) });
  assert.equal(summarizeMarketDemand([left, right], ["own-product"], asOf, 30, null).get("own-product")!.expectedDemand, null);
  assert.equal(summarizeMarketDemand([wide], ["own-product"], asOf, 30, null).get("own-product")!.expectedDemand, null);
});

test("complete daily zero demand stays zero; missing products and negative predictions remain unavailable", () => {
  const daily = Array.from({ length: 30 }, (_, day) => forecast(day, 0));
  const result = summarizeMarketDemand(daily, ["own-product", "missing-product"], asOf, 30, null);
  assert.equal(result.get("own-product")!.expectedDemand, 0);
  assert.equal(result.get("missing-product")!.expectedDemand, null);
  daily[2]!.expected_demand = -1;
  assert.equal(summarizeMarketDemand(daily, ["own-product"], asOf, 30, null).get("own-product")!.expectedDemand, null);
});

test("a newer foreign-currency observation does not hide the comparable price", () => {
  const observations = [
    { currency: "USD", observed_at: asOf, scraped_price: 999 },
    { currency: "JOD", observed_at: addDays(asOf, -2), scraped_price: 12 }
  ];
  assert.equal(comparableMarketPrice(observations, "JOD", asOf, null), 12);
  assert.equal(comparableMarketPrice(observations, "EUR", asOf, null), null);
  assert.equal(comparableMarketPrice(observations, "JOD", asOf, 1), null);
  assert.equal(comparableMarketPrice([{ currency: "JOD", observed_at: addDays(asOf, 1), scraped_price: 2 }], "JOD", asOf, null), null);
});

test("freshness has no invented cutoff and excludes old forecasts only with a configured age policy", () => {
  assert.equal(sourceAgePolicy(undefined), null);
  assert.equal(sourceAgePolicy("2"), 2);
  for (const value of ["0", "-1", "NaN"]) assert.throws(() => sourceAgePolicy(value));
  assert.equal(sourceFreshness(addDays(asOf, -100), asOf, null).status, "not_assessed");
  assert.equal(sourceFreshness(addDays(asOf, -2), asOf, 2).status, "current");
  assert.equal(sourceFreshness(addDays(asOf, -3), asOf, 2).status, "stale");
  assert.equal(sourceFreshness(null, asOf, null).status, "unknown");
  const old = forecast(29, 400, { forecast_start_date: start, forecast_end_date: addDays(start, 29), created_at: addDays(asOf, -3) });
  assert.equal(summarizeMarketDemand([old], ["own-product"], asOf, 30, 2).get("own-product")!.expectedDemand, null);
  assert.equal(summarizeMarketDemand([old], ["own-product"], asOf, 30, null).get("own-product")!.expectedDemand, 400);
});

test("section status accounts for every row and distinguishes partial/stale/unavailable", () => {
  assert.equal(aggregateMarketStatus(["verified", "unavailable"]), "partial");
  assert.equal(aggregateMarketStatus(["derived", "stale"]), "partial");
  assert.equal(aggregateMarketStatus(["stale", "stale"]), "stale");
  assert.equal(aggregateMarketStatus(["verified", "derived"]), "derived");
  assert.equal(aggregateMarketStatus([]), "unavailable");
});
