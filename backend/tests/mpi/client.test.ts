import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { requestMarketIntelligence } from "../../src/modules/mpi/client/mpi.client.js";
const texts = Array.from({ length: 5 }, (_, index) => `Review ${index}`);
const input = { reviews: texts.map((text) => ({ text, review_date: "2026-10-10", collection_method: "MANUAL" as const })), subjectType: "PRODUCT" as const, subjectId: "product" };
function response() {
  return {
    sentiment_model: "model", sentiment_model_revision: "revision", classification: {},
    reviews: texts.map((text, index) => ({ review_id: index, text, label: "positive", sentiment_score: 0.8, confidence: 0.9 })),
    mpi: { status: "OK", mpi: 70, sample_size: 5, review_count: 5, weighted_sentiment_score: 0.8, volume_confidence: 0.5,
      avg_recency_weight: 1, avg_reliability_weight: 0.6, label_counts: { positive: 5, neutral: 0, negative: 0 } },
    evidence_record: { explanation_text: "Sample evidence", confidence_score: 0.8 }
  };
}
test("known numeric and structured sample metadata are accepted without inferring sufficiency", async () => {
  const numeric = await requestMarketIntelligence(input, { call: async () => response() });
  assert.equal(numeric.mpi.sample_size, 5);
  const structured = response();
  Object.assign(structured.mpi, { sample_size: { status: "LOW_SAMPLE_SIZE", minimum_required: 10, review_count: 5 } });
  const result = await requestMarketIntelligence(input, { call: async () => structured });
  assert.equal(typeof result.mpi.sample_size === "object" && result.mpi.sample_size.status, "LOW_SAMPLE_SIZE");
});
test("the supplied hosted example accepts uppercase labels and analyzed_count metadata", async () => {
  const fixture = JSON.parse(readFileSync(new URL("./fixtures/hosted-market-intelligence.json", import.meta.url), "utf8"));
  const calls: any[] = [];
  const result = await requestMarketIntelligence(fixture.input, { call: async (request) => { calls.push(request); return fixture.response; } });
  assert.equal(calls[0].apiName, "market_intelligence");
  assert.equal(calls[0].data[1], "BUSINESS");
  assert.equal(calls[0].data[2], null);
  assert.equal(result.mpi.mpi, 55.91);
  assert.deepEqual(result.reviews.map((review) => review.label), ["positive", "negative", "positive", "positive", "negative", "positive"]);
  assert.deepEqual(result.mpi.label_counts, { positive: 4, neutral: 0, negative: 2 });
  assert.deepEqual(result.mpi.sample_size, { status: "OK", minimum_required: 5, analyzed_count: 6, sufficient: true });
  assert.equal(result.evidence_record.confidence_score, 0.57);
});
test("both hosted and legacy sample counts must agree with the analyzed subset", async () => {
  for (const sample_size of [
    { status: "OK", sufficient: true, minimum_required: 5, analyzed_count: 6 },
    { status: "OK", sufficient: true, minimum_required: 5, analyzed_count: 5, review_count: 6 }
  ]) {
    const value = response(); Object.assign(value.mpi, { sample_size });
    await assert.rejects(requestMarketIntelligence(input, { call: async () => value }), (error: any) => error.kind === "malformed_response");
  }
});
test("malformed scores, inconsistent counts/labels and foreign review text fail closed", async () => {
  for (const alter of [
    (value: any) => { value.mpi.mpi = 101; },
    (value: any) => { value.mpi.sample_size = "OK"; },
    (value: any) => { value.mpi.review_count = 6; },
    (value: any) => { value.mpi.sample_size = 7; },
    (value: any) => { value.mpi.label_counts = { positive: 0, neutral: 5, negative: 0 }; },
    (value: any) => { value.reviews[0].text = "Different tenant's text"; },
    (value: any) => { value.evidence_record.confidence_score = 1.1; },
    (value: any) => { value.mpi.mpi = null; },
    (value: any) => { value.reviews[0].label = "MIXED"; },
    (value: any) => { value.mpi.sample_size = { status: "OK", analyzed_count: -1 }; },
    (value: any) => { value.mpi.sample_size = { status: "OK", sufficient: "true" }; }
  ]) {
    const value = response(); alter(value);
    await assert.rejects(requestMarketIntelligence(input, { call: async () => value }), (error: any) => error.kind === "malformed_response");
  }
});
