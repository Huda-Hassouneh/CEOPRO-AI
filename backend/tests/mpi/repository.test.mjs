import assert from "node:assert/strict";
import { mock, test } from "node:test";
let owner = true, calls = [], batches = [], saved;
const asOf = new Date("2026-10-12T00:00:00Z");
const tx = {
  $queryRaw: async (parts, ...args) => { calls.push({ sql: parts.join("?"), args }); return []; },
  company: { findFirst: async (query) => { calls.push({ company: query }); return { countryCode: "JO" }; } },
  products: { findFirst: async (query) => { calls.push({ product: query }); return owner ? { product_id: "product" } : null; } },
  tenant_competitors: { findFirst: async (query) => { calls.push({ competitor: query }); return owner ? { global_competitor_id: "competitor" } : null; } },
  reviews: { findMany: async (query) => { calls.push({ reviews: query }); return batches.shift() ?? []; } },
  evidence_records: { create: async (query) => { saved = query; return { evidence_id: "evidence" }; } }
};
await mock.module("../../src/config/database.ts", { namedExports: { prisma: { $transaction: async (callback) => callback(tx) } } });
const { getReviewsForMpi, persistMpiEvidence } = await import("../../src/modules/mpi/repo/mpi.repo.ts");
const base = { tenantId: "tenant", userId: "user", asOf };
test("business query is explicitly business-only and runs under tenant/user RLS context", async () => {
  calls = []; batches = [];
  await getReviewsForMpi({ ...base, subjectType: "BUSINESS" });
  assert.deepEqual(calls[0].args, ["tenant", "user"]);
  const query = calls.find((entry) => entry.reviews).reviews;
  assert.equal(query.where.subject_type, "BUSINESS");
  assert.equal(query.where.product_id, null); assert.equal(query.where.competitor_id, null);
  assert.equal(query.where.source_status, "ALLOWED"); assert.equal(query.where.safety_status, "SAFE");
  assert.deepEqual(query.where.review_date, { lte: asOf });
});
test("product and tracked-competitor ownership is checked before loading review text", async () => {
  for (const [subjectType, subjectId] of [["PRODUCT", "product"], ["COMPETITOR", "competitor"]]) {
    owner = false; calls = [];
    await assert.rejects(getReviewsForMpi({ ...base, subjectType, subjectId }), (error) => error.code === "SUBJECT_NOT_FOUND");
    assert.equal(calls.some((entry) => entry.reviews), false);
    owner = true; calls = []; batches = [];
    await getReviewsForMpi({ ...base, subjectType, subjectId });
    const query = calls.find((entry) => entry.reviews).reviews;
    assert.equal(query.where.subject_type, subjectType);
    assert.equal(query.where.tenant_id, "tenant");
    if (subjectType === "PRODUCT") {
      assert.equal(query.where.product_id, subjectId);
      assert.equal(calls.find((entry) => entry.product).product.where.deleted_at, null);
    } else {
      assert.equal(query.where.competitor_id, subjectId);
      assert.equal(calls.find((entry) => entry.competitor).competitor.where.is_tracked, true);
    }
  }
});
test("blank text does not consume the usable sample slots", async () => {
  batches = [Array.from({ length: 100 }, (_, index) => ({ review_id: `blank-${index}`, review_text: "   ", review_date: asOf, collection_method: "MANUAL" })),
    [{ review_id: "real", review_text: "Actual review", review_date: asOf, collection_method: "PUBLIC_API" }]];
  const result = await getReviewsForMpi({ ...base, subjectType: "BUSINESS" });
  assert.deepEqual(result.reviews.map((review) => review.review_id), ["real"]);
});
test("evidence stores real review references, sample scope and the subject context", async () => {
  const evidence = { source_review_ids: ["real"], source_scope: "submitted_sample", explanation: "Evidence", observation_period: { start: asOf.toISOString(), end: asOf.toISOString() }, collection_methods: ["MANUAL"], sample_limit: 100, eligible_review_count: 1, sentiment_model: "model", model_revision: "rev" };
  await persistMpiEvidence({ ...base, subjectType: "BUSINESS", subjectId: "tenant", status: "UNKNOWN", reason: "INSUFFICIENT_REVIEWS", mpi: null, reviewCount: 1,
    weightedSentimentScore: 0.5, volumeConfidence: 0.1, explanationText: "Evidence", confidenceScore: 0.1, evidence, asOf: asOf.toISOString(),
    sampleSize: { status: "LOW_SAMPLE_SIZE", minimum_required: 5, observed: 1 }, labelCounts: { positive: 1, neutral: 0, negative: 0 } });
  assert.deepEqual(saved.data.source_record_ids.review_ids, ["real"]);
  assert.equal(saved.data.source_record_ids.review_id_scope, "submitted_sample");
  assert.equal(saved.data.metric_value_json.mpi, null);
  assert.equal(saved.data.tenant_id, "tenant");
});
