import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { coveragePresentation, prepareForecastExport } from "../src/features/forecasting/utils/forecastPresentation.js";
import { isForecastRefreshBusy } from "../src/features/forecasting/utils/forecastRefresh.js";
test("coverage preserves zero, bounds counts and distinguishes stale/partial from complete", () => {
  assert.deepEqual(coveragePresentation({ status: "partial", coveredDays: 0, periodDays: 7 }, 30), { status: "partial", covered: 0, total: 7 });
  assert.equal(coveragePresentation({ status: "stale" }, 30).status, "stale");
  assert.equal(coveragePresentation({ status: "unexpected" }, 7).status, "unavailable");
});
test("PDF sanitization strips unauthorized recommendations without changing the source", () => {
  const data = { recommendation: { action: "restock" }, recommendationStatus: { reason: "STOCK_CHANGED" }, forecasts: [{ recommendedAction: "restock", suggestedQuantity: 42, recommendation: { secret: true }, recommendationStatus: { reason: "STOCK_CHANGED" } }] };
  const clean = prepareForecastExport(data);
  assert.equal(clean.recommendation, null); assert.equal(clean.forecasts[0].suggestedQuantity, null);
  assert.equal(clean.recommendationStatus, null); assert.equal(clean.forecasts[0].recommendationStatus, null);
  assert.equal(data.forecasts[0].suggestedQuantity, 42);
  assert.equal(prepareForecastExport(data, true).forecasts[0].suggestedQuantity, 42);
});
test("forecast generation and coverage translation keys match in Arabic and English", () => {
  const read = (lang) => JSON.parse(readFileSync(new URL(`../src/assets/locales/${lang}.json`, import.meta.url))).demandApproved;
  const flatten = (item, path = "") => Object.entries(item).flatMap(([k,v]) => typeof v === "object" ? flatten(v, `${path}${k}.`) : [`${path}${k}`]).sort();
  assert.deepEqual(flatten(read("en")), flatten(read("ar")));
});
test("only a database-busy refresh with existing query data can retain the forecast page", () => {
  const query = { isError: true, data: { product: { id: "selected" } }, error: { response: { status: 503, data: { error: { code: "SERVICE_UNAVAILABLE", details: { reason: "FORECAST_DATABASE_BUSY" } } } } } };
  assert.equal(isForecastRefreshBusy(query), true);
  assert.equal(isForecastRefreshBusy({ ...query, data: undefined }), false);
  assert.equal(isForecastRefreshBusy({ ...query, isError: false }), false);
  for (const status of [401, 403, 404, 500]) assert.equal(isForecastRefreshBusy({ ...query, error: { response: { ...query.error.response, status } } }), false);
  assert.equal(isForecastRefreshBusy({ ...query, error: { response: { status: 503, data: {} } } }), false);
});
