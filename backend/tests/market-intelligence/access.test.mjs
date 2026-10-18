import assert from "node:assert/strict";
import { mock, test } from "node:test";

let features = new Set();
let exhausted = false;
let mpiCalls = 0;
let mpiBehavior = "ok";
let repoArguments;
const rawData = {
  competitors: [{ competitorId: "competitor", dataStatus: "derived", marketPerception: null, marketPerceptionScore: null }],
  pricingRecommendations: [{ productId: "product", currentPrice: 10, marketAverage: 12, action: "raise", suggestedPrice: 11, explanation: "derived" }]
};
await mock.module("../../src/modules/features/repo/usage.repo.ts", {
  namedExports: {
    getFeatureAccessInfo: async (_tenant, code) => ({ subscription: { id: "sub" }, planFeature: features.has(code) ? {} : null }),
    getRemainingUsage: async () => ({ isUnlimited: false, isExceeded: exhausted, aggregationType: "sum" })
  }
});
await mock.module("../../src/modules/market-intelligence/repo/market-int.repo.ts", {
  namedExports: { getMarketIntelligence: async (...args) => { repoArguments = args; return structuredClone(rawData); } }
});
await mock.module("../../src/modules/mpi/service/mpi.service.ts", {
  namedExports: { getMpiSummary: async () => {
    mpiCalls += 1;
    if (mpiBehavior === "failure") throw new Error("fixture service unavailable");
    if (mpiBehavior === "thin") return { status: "UNKNOWN", reason: "INSUFFICIENT_REVIEWS", sample_size: { status: "LOW_SAMPLE_SIZE", minimum_required: 5, observed: 3 }, review_count: 3 };
    return { status: "OK", sample_size: { status: "OK", minimum_required: 5, observed: 5 }, review_count: 5, analysis_performed: true, mpi: 75, label_counts: { positive: 5, neutral: 0, negative: 0 } };
  } }
});

const { getMarketIntelligence } = await import("../../src/modules/market-intelligence/service/market-int.service.ts");
const { requireEntitlement, requireFeatureAccess } = await import("../../src/middleware/validators/validateFeatures.ts");

async function decision(middleware) {
  const result = { status: null, payload: null, allowed: false };
  const res = { status(value) { result.status = value; return this; }, json(value) { result.payload = value; return this; } };
  await middleware({ tenant_id: "tenant" }, res, () => { result.allowed = true; });
  return result;
}

test("overview makes no MPI call without its entitlement and preserves regular market statistics", async () => {
  features = new Set(["market_intelligence"]);
  const result = await getMarketIntelligence("tenant", "user", "product", 30);
  assert.equal(mpiCalls, 0);
  assert.deepEqual(result.featureAccess, { marketPerception: false, aiPricing: false, demandPrediction: false });
  assert.equal(repoArguments[1], "user");
  assert.deepEqual(repoArguments[4], { includeDemand: false });
  assert.equal(result.pricingRecommendations[0].marketAverage, 12);
  assert.equal(result.pricingRecommendations[0].action, null);
  assert.equal(result.pricingRecommendations[0].suggestedPrice, null);
});

test("permitted MPI enrichment and demand/AI pricing remain available", async () => {
  features = new Set(["market_perception", "ai_pricing", "demand_prediction"]);
  const result = await getMarketIntelligence("tenant", "user", "product", 90);
  assert.equal(mpiCalls, 1);
  assert.equal(result.competitors[0].marketPerceptionScore, 75);
  assert.deepEqual(repoArguments[4], { includeDemand: true });
  assert.equal(result.pricingRecommendations[0].action, "raise");
});

test("actual entitlement middleware rejects missing access and exhausted pricing allowance", async () => {
  features = new Set(); exhausted = false;
  const blocked = await decision(requireEntitlement("market_intelligence"));
  assert.equal(blocked.status, 403);
  assert.equal(blocked.allowed, false);
  assert.equal(blocked.payload.error.details.reason, "FEATURE_NOT_INCLUDED");
  assert.equal((await decision(requireFeatureAccess("market_perception"))).status, 403);
  features = new Set(["ai_pricing"]); exhausted = true;
  const quota = await decision(requireEntitlement("ai_pricing"));
  assert.equal(quota.status, 402);
  assert.equal(quota.payload.error.details.reason, "QUOTA_EXHAUSTED");
  exhausted = false;
  assert.equal((await decision(requireEntitlement("ai_pricing"))).allowed, true);
});


test("thin samples and service failures remain distinct in an otherwise available overview", async () => {
  features = new Set(["market_perception"]);
  mpiBehavior = "thin";
  const thin = await getMarketIntelligence("tenant", "user", "product", 30);
  assert.equal(thin.competitors[0].marketPerceptionStatus, "INSUFFICIENT_REVIEWS");
  assert.equal(thin.competitors[0].marketPerceptionScore, null);
  assert.equal(thin.sectionStatuses.competitors, "partial");
  mpiBehavior = "failure";
  const failure = await getMarketIntelligence("tenant", "user", "product", 30);
  assert.equal(failure.competitors[0].marketPerceptionStatus, "SERVICE_UNAVAILABLE");
  assert.equal(failure.competitors[0].marketPerceptionSummary, null);
  mpiBehavior = "ok";
});
