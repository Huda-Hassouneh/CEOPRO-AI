import assert from "node:assert/strict";
import { test } from "node:test";
import { aggregateSectionStatus, buildPricingRows, prepareMarketExport, pricingErrorMessage } from "../src/features/market-intelligence/utils/marketIntelligencePresentation.js";

const product = { id: "own", name: "Own", currency: "JOD" };
const row = { productId: "own", currentPrice: 10, marketMin: 8, marketMax: 12, marketAverage: 10, matchedCompetitors: 2, action: "raise", suggestedPrice: 11, explanation: "derived", dataStatus: "derived" };

test("ordinary comparison keeps competitor counts but never displays a generated action before AI returns", () => {
  const result = buildPricingRows({ selectedProduct: product, overviewRows: [row] });
  assert.equal(result[0].matchedCompetitors, 2);
  assert.equal(result[0].action, null);
  assert.equal(result[0].suggestedPrice, null);
  assert.deepEqual(buildPricingRows({ selectedProduct: product, overviewRows: [{ ...row, productId: "foreign" }] }), []);
});

test("AI result never relabels JOD fallback prices as USD and UNKNOWN has no action", () => {
  const result = buildPricingRows({ selectedProduct: product, overviewRows: [row], recommendation: { status: "OK", currency: "USD", action: "hold", suggested_price: 20 } });
  assert.equal(result[0].marketMin, null);
  assert.equal(result[0].currentPrice, null);
  const unknown = buildPricingRows({ selectedProduct: product, overviewRows: [row], recommendation: { status: "UNKNOWN", action: "raise", suggested_price: 25 } });
  assert.equal(unknown[0].action, null);
  assert.equal(unknown[0].suggestedPrice, null);
});

test("PDF data is redacted for optional features without altering ordinary prices or the original payload", () => {
  const data = { featureAccess: { marketPerception: true, aiPricing: true }, competitors: [{ marketPerception: "positive", marketPerceptionScore: 80 }], pricingRecommendations: [row] };
  const exported = prepareMarketExport(data, {});
  assert.equal(exported.competitors[0].marketPerception, null);
  assert.equal(exported.pricingRecommendations[0].action, null);
  assert.equal(exported.pricingRecommendations[0].marketAverage, 10);
  assert.equal(exported.featureAccess.aiPricing, false);
  assert.equal(data.competitors[0].marketPerception, "positive");
  const allowed = prepareMarketExport(data, { marketPerception: true, aiPricing: true });
  assert.equal(allowed.competitors[0].marketPerceptionScore, 80);
  assert.equal(allowed.pricingRecommendations[0].suggestedPrice, 11);
});

test("section status does not depend on the first row", () => {
  assert.equal(aggregateSectionStatus([{ dataStatus: "verified" }, { dataStatus: "unavailable" }]), "partial");
  assert.equal(aggregateSectionStatus([{ dataStatus: "unavailable" }, { dataStatus: "verified" }]), "partial");
  assert.equal(aggregateSectionStatus([{ dataStatus: "stale" }]), "stale");
  assert.equal(aggregateSectionStatus([]), "unavailable");
});

test("pricing failures use translated quota, missing-feature, and upstream messages", () => {
  const t = (key) => key;
  assert.equal(pricingErrorMessage({ response: { data: { error: { details: { reason: "QUOTA_EXHAUSTED" } } } } }, t), "marketMain.error.pricingQuotaExhausted");
  assert.equal(pricingErrorMessage({ response: { data: { error: { details: { reason: "FEATURE_NOT_INCLUDED" } } } } }, t), "marketMain.error.pricingNotIncluded");
  assert.equal(pricingErrorMessage({ response: { status: 502, data: { error: { code: "EXTERNAL_SERVICE_ERROR", message: "External service error" } } } }, t), "apiErrors.EXTERNAL_SERVICE_ERROR");
});
