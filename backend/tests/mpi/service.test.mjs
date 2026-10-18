import assert from "node:assert/strict";
import { mock, test } from "node:test";
let included = true, records = [], calls = [], saved = [], provider, scopeError;
const now = new Date();
const reviews = (count) => Array.from({ length: count }, (_, index) => ({
  review_id: `review-${index}`, review_text: ` Text ${index} `,
  review_date: new Date(now.getTime() - (index + 1) * 86_400_000), collection_method: "MANUAL"
}));
function result(count = 5) {
  return { sentiment_model: "model", sentiment_model_revision: "revision",
    evidence_record: { explanation_text: "Five supporting reviews", confidence_score: 0.8 },
    mpi: { status: "OK", mpi: 70, sample_size: count, review_count: count,
      label_counts: { positive: count, neutral: 0, negative: 0 }, weighted_sentiment_score: 0.8,
      volume_confidence: 0.5, avg_recency_weight: 1, avg_reliability_weight: 0.6 } };
}
await mock.module("../../src/modules/features/repo/usage.repo.ts", { namedExports: {
  getFeatureAccessInfo: async () => ({ subscription: {}, planFeature: included ? {} : null })
} });
await mock.module("../../src/modules/mpi/repo/mpi.repo.ts", { namedExports: {
  getReviewsForMpi: async () => { if (scopeError) throw scopeError; return { reviews: records, countryCode: "JO" }; },
  persistMpiEvidence: async (value) => { saved.push(value); return "evidence"; }
} });
await mock.module("../../src/modules/mpi/client/mpi.client.ts", { namedExports: {
  isMpiClientError: (error) => error?.name === "AiIntegrationError",
  requestMarketIntelligence: async (value) => { calls.push(value); if (provider instanceof Error) throw provider; return provider; }
} });
const { getMpiSummary } = await import("../../src/modules/mpi/service/mpi.service.ts");
const input = { tenantId: "tenant", userId: "user", subjectType: "PRODUCT", subjectId: "product" };

test("no/thin reviews skip provider calls and expose truthful counts and missing-data reasons", async () => {
  records = []; calls = []; saved = [];
  let response = await getMpiSummary(input);
  assert.equal(response.reason, "NO_ELIGIBLE_REVIEWS"); assert.equal(response.review_count, 0);
  records = reviews(4); response = await getMpiSummary(input);
  assert.equal(response.reason, "INSUFFICIENT_REVIEWS"); assert.equal(response.sample_size.observed, 4);
  assert.equal(response.analysis_performed, false); assert.equal(response.mpi, undefined);
  assert.equal(calls.length, 0); assert.equal(saved.length, 0);
});
test("OK results include tenant-bound source references, dates, model and evidence confidence", async () => {
  records = reviews(5); provider = result(); calls = []; saved = [];
  const response = await getMpiSummary(input);
  assert.equal(response.status, "OK"); assert.equal(response.mpi, 70);
  assert.equal(response.confidence_score, 0.8); assert.equal(response.evidence_id, "evidence");
  assert.deepEqual(response.evidence.source_review_ids, records.map((record) => record.review_id));
  assert.equal(response.evidence.source_scope, "submitted_sample");
  assert.equal(saved[0].tenantId, "tenant"); assert.equal(saved[0].subjectId, "product");
  assert.equal(calls[0].reviews[0].text, "Text 0"); assert.ok(calls[0].asOf);
});
test("model low-sample/unknown/higher minimum states never publish a provisional score", async () => {
  records = reviews(5);
  for (const sample of [{ status: "LOW_SAMPLE_SIZE" }, { status: "UNKNOWN" }, { status: "OK", minimum_required: 10 }, { status: "OK", sufficient: false, analyzed_count: 5 }]) {
    provider = result(); provider.mpi.sample_size = sample;
    const response = await getMpiSummary(input);
    assert.equal(response.status, "UNKNOWN"); assert.equal(response.mpi, undefined);
    assert.equal(saved.at(-1).mpi, null);
  }
  provider = result(); provider.mpi.status = "LOW_SAMPLE_SIZE";
  assert.equal((await getMpiSummary(input)).reason, "INSUFFICIENT_REVIEWS");
});
test("internal access checks prevent bypass and business evidence uses the signed-in tenant", async () => {
  included = false;
  await assert.rejects(getMpiSummary(input), (error) => error.code === "FEATURE_NOT_INCLUDED");
  included = true; provider = result(); records = reviews(5);
  const response = await getMpiSummary({ tenantId: "tenant", userId: "user", subjectType: "BUSINESS" });
  assert.equal(response.subject_id, "tenant"); assert.equal(saved.at(-1).subjectId, "tenant");
  await assert.rejects(getMpiSummary({ tenantId: "tenant", userId: "user", subjectType: "BUSINESS", subjectId: "foreign" }));
});

test("zero usable model contributions do not falsely report that the tenant has no reviews", async () => {
  records = reviews(5); provider = result(0); provider.mpi.status = "UNKNOWN"; provider.mpi.mpi = null;
  const response = await getMpiSummary(input);
  assert.equal(response.status, "UNKNOWN");
  assert.equal(response.reason, "MODEL_UNAVAILABLE");
  assert.equal(response.review_count, 0);
  assert.equal(response.evidence.eligible_review_count, 5);
});
test("upstream failures remain failures instead of becoming successful low-sample results", async () => {
  records = reviews(5); provider = new Error("upstream failed");
  await assert.rejects(getMpiSummary(input), /upstream failed/);
});


test("controller maps subject/access/upstream failures to public HTTP errors", async () => {
  const { getSummary } = await import("../../src/modules/mpi/controller/mpi.controller.ts");
  const { MpiSubjectError } = await import("../../src/modules/mpi/service/mpi.policy.ts");
  const req = { tenant_id: "tenant", user: { user_id: "user" }, query: { subject_type: "PRODUCT", subject_id: "product" } };
  async function invoke() {
    let status, payload;
    const res = { status(value) { status = value; return this; }, json(value) { payload = value; return this; } };
    await getSummary(req, res, (error) => { throw error; });
    return { status, payload };
  }
  included = true; scopeError = new MpiSubjectError("SUBJECT_NOT_FOUND");
  assert.equal((await invoke()).status, 404);
  scopeError = undefined;
  included = false; assert.equal((await invoke()).status, 403); included = true;
  provider = new Error("provider timeout"); provider.name = "AiIntegrationError";
  const failure = await invoke();
  assert.equal(failure.status, 502);
  assert.equal(failure.payload.error.code, "EXTERNAL_SERVICE_ERROR");
});
