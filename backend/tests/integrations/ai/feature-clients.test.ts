import assert from "node:assert/strict";
import test from "node:test";
import type { GradioCallInput, GradioClient } from "../../../src/integrations/ai/ai.types.js";
import { uploadExtractionFile } from "../../../src/modules/dataconnection/client/ingestion.client.js";
import { requestDemandForecast } from "../../../src/modules/forecasting/client/forecasting.client.js";
import { requestMarketIntelligence } from "../../../src/modules/mpi/client/mpi.client.js";
import { requestPricingRecommendation } from "../../../src/modules/pricing/client/pricing.client.js";
import { queryRagAi } from "../../../src/modules/rag/client/rag.client.js";
import { requestSentimentClassification } from "../../../src/modules/sentiment/client/sentiment.client.js";

function stubClient(payload: unknown, calls: GradioCallInput[]): GradioClient {
  return { call: async (input) => { calls.push(input); return payload; } };
}

test("extraction client sends the documented four positional arguments", async () => {
  const calls: GradioCallInput[] = [];
  const result = await uploadExtractionFile({
    file: { originalname: "sales data.csv", buffer: Buffer.from("a,b\n1,2") }
  }, stubClient({
    file_name: "sales_data.csv", detected_type: "csv", headers: ["a", "b"],
    rows_processed: 1, rows_truncated_to_limit: false, staged_row_count: 1,
    summary: {
      template_mode: "generic", header_coverage_ratio: 1, rows_processed: 1,
      rows_partial: 0, rows_failed: 0, total_fields_expected: 2,
      total_fields_extracted: 2, row_outcomes: []
    }
  }, calls));

  assert.equal(result.rows_processed, 1);
  assert.deepEqual(calls[0], {
    service: "analytics", apiName: "extract_file",
    data: ["sales data.csv", Buffer.from("a,b\n1,2").toString("base64"), "JO", "JOD"],
    timeoutMs: undefined
  });
});

test("MPI client preserves optional positional values and validates provider output", async () => {
  const calls: GradioCallInput[] = [];
  await requestMarketIntelligence({
    reviews: [{ text: "Great", review_date: "2026-01-01", collection_method: "MANUAL" }],
    subjectType: "PRODUCT", subjectId: "product-1", countryCode: "JO", asOf: "2026-01-02"
  }, stubClient({
    sentiment_model: "model", sentiment_model_revision: "rev", classification: {},
    reviews: [{ review_id: "r1", text: "Great", label: "positive", sentiment_score: 0.9, confidence: 0.9 }],
    mpi: {
      status: "OK", mpi: 90, sample_size: 1, weighted_sentiment_score: 0.8,
      volume_confidence: 0.5, review_count: 1, avg_recency_weight: 1,
      avg_reliability_weight: 1, label_counts: { positive: 1, neutral: 0, negative: 0 }
    }, evidence_record: { explanation_text: "Evidence", confidence_score: 0.8 }
  }, calls));
  assert.deepEqual(calls[0]?.data, [[{
    text: "Great", review_date: "2026-01-01", collection_method: "MANUAL"
  }], "PRODUCT", "product-1", "JO", "2026-01-02"]);
  assert.equal(calls[0]?.apiName, "market_intelligence");
});

test("forecast client rejects invalid horizon before making an upstream call", async () => {
  const calls: GradioCallInput[] = [];
  await assert.rejects(requestDemandForecast({
    transactions: [], horizonDays: 61, currentPrice: null, currentStock: null,
    currency: "JOD", productName: "Coffee"
  }, stubClient({}, calls)), /between 1 and 60 days/);
  assert.equal(calls.length, 0);
});

test("pricing client sends product, competitor, and exchange-rate arguments", async () => {
  const calls: GradioCallInput[] = [];
  const request = {
    product: { product_name: "Coffee", current_price: 10, currency: "JOD", cost_price: 6 },
    competitorPrices: [{ competitor_name: "Shop A", price: 11, currency: "JOD", observed_at: "2026-01-01" }],
    exchangeRates: null
  };
  await requestPricingRecommendation(request, stubClient({
    result: { status: "UNKNOWN" }, persisted_records: []
  }, calls));
  assert.equal(calls[0]?.service, "analytics");
  assert.equal(calls[0]?.apiName, "recommend");
  assert.deepEqual(calls[0]?.data, [request.product, request.competitorPrices, null]);
});

test("sentiment client batches texts and rejects mismatched result counts", async () => {
  const calls: GradioCallInput[] = [];
  const client = stubClient({ model: "m", model_revision: "r", results: [] }, calls);
  await assert.rejects(requestSentimentClassification(["good"], client), /count did not match/);
  assert.deepEqual(calls[0], {
    service: "models", apiName: "sentiment", data: [["good"]], timeoutMs: 60_000
  });
});

test("RAG client sends documents, question, top-k, and history in order", async () => {
  const calls: GradioCallInput[] = [];
  await queryRagAi({
    documents: [{ file_name: "guide.txt", text: "Returns are accepted within 30 days." }],
    queryText: "What is the return window?", topK: 5, history: null
  }, stubClient({ answer: "30 days", sources: [] }, calls));
  assert.equal(calls[0]?.service, "models");
  assert.equal(calls[0]?.apiName, "rag_answer");
  assert.deepEqual(calls[0]?.data, [[{
    file_name: "guide.txt", text: "Returns are accepted within 30 days."
  }], "What is the return window?", 5, null]);
  assert.equal(calls[0]?.timeoutMs, 120_000);
});
