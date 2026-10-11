import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (relative) => readFile(new URL(relative, import.meta.url), "utf8");
const withoutComments = (source) => source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

test("ai_pricing catalog is a SUM recommendation allowance reset each billing period", async () => {
  const catalog = await read("../../src/modules/features/catalog.ts");
  const feature = catalog.match(/\{\s*code: "ai_pricing"[\s\S]*?\n  \},/);
  assert.ok(feature, "canonical ai_pricing feature is registered");
  assert.match(feature[0], /FeatureType\.limit/);
  assert.match(feature[0], /AggregationType\.sum/);
  assert.match(feature[0], /ResetCycle\.billing_period/);
  assert.match(feature[0], /recommendations/i);
});

test("Starter, Growth, and Enterprise plans do not grant AI Pricing", async () => {
  const source = await read("../../src/config/production-plans.ts");
  for (const plan of ["starter", "growth", "enterprise"]) {
    const section = source.match(new RegExp(`code: "${plan}"[\\s\\S]*?(?=code: "|\\n  },)`, "i"));
    assert.ok(section, `${plan} plan is present`);
    assert.doesNotMatch(section[0], /ai_pricing/);
  }
});

test("custom-plan persistence preserves the caller's feature ID and recommendation limit", async () => {
  const feature = (await read("../../src/modules/features/catalog.ts")).match(/\{\s*code: "ai_pricing"[\s\S]*?\n  \},/);
  const quoteRepo = await read("../../tests/billing/custom-plan/08-promo-entitlements-contract.scenario.ts");
  const usageRepo = await read("../../src/modules/features/repo/usage.repo.ts");
  assert.ok(feature);
  assert.match(feature[0], /FeatureType\.limit/);
  assert.match(quoteRepo, /quote\.quoteFeatures\.map[\s\S]*?feature_id: feature\.featureId[\s\S]*?limit_value: feature\.limitValue/);
  assert.match(usageRepo, /planFeatures[\s\S]*?limit_value/);
});

test("pricing route enforces the ai_pricing entitlement before invoking the controller", async () => {
  const route = withoutComments(await read("../../src/modules/pricing/route/pricing.route.ts"));
  assert.match(route, /authenticateUser/);
  assert.match(route, /requireTenant/);
  assert.ok(/requireEntitlement\(["']ai_pricing["']\)[,\s\n]*recommendPrice/.test(route),
    "AI_PRICING_ENTITLEMENT_BYPASS: POST /features/pricing/recommend must deny tenants without an active allocation before provider invocation.");
});

test("pricing request is server-scoped to authenticated tenant and validates product UUID", async () => {
  const route = await read("../../src/modules/pricing/route/pricing.route.ts");
  const controller = await read("../../src/modules/pricing/controller/pricing.controller.ts");
  const validation = await read("../../src/modules/pricing/types/pricing.validation.ts");
  assert.match(route, /authenticateUser, requireTenant/);
  assert.match(controller, /tenantId\s*=\s*req\.tenant_id/);
  assert.match(controller, /userId\s*=\s*req\.user\?\.user_id/);
  assert.match(validation, /product_id[\s\S]*?\.uuid\(/);
  assert.doesNotMatch(controller, /req\.query\.tenant_id/);
});

test("effective allocation is reserved or checked before a paid Gradio invocation", async () => {
  const service = await read("../../src/modules/pricing/service/pricing.service.ts");
  const provider = service.indexOf("requestPricingRecommendation({");
  const usage = service.indexOf("incrementUsage(input.tenantId, \"ai_pricing\")");
  assert.ok(provider >= 0 && usage >= 0);
  assert.ok(/reserve|remaining|entitlement|limit/i.test(service.slice(0, provider)),
    "AI_PRICING_QUOTA_EXCEEDED: the service must reject or reserve quota before calling the paid provider.");
  assert.ok(usage < provider, "AI_PRICING_USAGE_NOT_CHARGED: charge/reservation must precede the provider call or use an atomic reservation protocol.");
});

test("missing-usage allocation cannot silently return a successful paid recommendation", async () => {
  const service = await read("../../src/modules/pricing/service/pricing.service.ts");
  const usageIndex = service.indexOf("incrementUsage(input.tenantId, \"ai_pricing\")");
  const tail = service.slice(usageIndex, usageIndex + 350);
  assert.match(tail, /if\s*\(!?\w+\)|throw|isExceeded|remaining/, 
    "AI_PRICING_USAGE_NOT_CHARGED: incrementUsage's null/missing-allocation result is not checked.");
});

test("recommendation evidence and outcome are committed together under tenant RLS", async () => {
  const repo = await read("../../src/modules/pricing/repo/pricing.repo.ts");
  assert.match(repo, /set_config\('app\.current_tenant_id'/);
  assert.match(repo, /set_config\('app\.current_user_id'/);
  assert.match(repo, /prisma\.\$transaction\(async \(tx\)/);
  assert.match(repo, /evidence_records\.create/);
  assert.match(repo, /recommendation_outcomes\.create/);
});

test("usage accounting participates in the same durable generation transaction", async () => {
  const service = await read("../../src/modules/pricing/service/pricing.service.ts");
  const repo = await read("../../src/modules/pricing/repo/pricing.repo.ts");
  assert.ok(repo.includes("prisma.$transaction") && service.includes("incrementUsage"));
  assert.match(service, /reserve|transaction|idempotency/i,
    "AI_PRICING_PERSISTENCE_FAILURE: evidence, outcome, and the charge are separate operations without an atomic reservation/reconciliation contract.");
});

test("a request idempotency key prevents duplicate provider work, evidence, outcomes, and charges", async () => {
  const route = await read("../../src/modules/pricing/route/pricing.route.ts");
  const service = await read("../../src/modules/pricing/service/pricing.service.ts");
  const schema = await read("../../prisma/schema.prisma");
  assert.match(route + service, /idempotency[-_]?key|request[-_]?id/i,
    "AI_PRICING_DUPLICATE_CHARGE: Generate/Refresh has no stable operation identity in the route/service.");
  assert.match(schema, /idempotency[-_]?key|request[-_]?id/i,
    "AI_PRICING_DUPLICATE_RECOMMENDATION: no persistence constraint protects retried operations.");
});

test("Node competitor inputs select only the latest eligible observation per tracked mapping", async () => {
  const repo = await read("../../src/modules/pricing/repo/pricing.repo.ts");
  assert.match(repo, /is_available:\s*true/);
  assert.match(repo, /is_exact_data:\s*true/);
  assert.match(repo, /source_status:\s*["']ALLOWED["']/);
  assert.match(repo, /is_active:\s*true/);
  assert.match(repo, /is_tracked:\s*true/);
  assert.match(repo, /observed_at:[\s\S]*?gte:/);
  assert.match(repo, /take:\s*1|DISTINCT\s+ON|row_number/i,
    "AI_PRICING_COMPETITOR_SELECTION_ERROR: every eligible historical observation may reach the model; no per-competitor latest-row collapse is present.");
});

test("Node FX rates are validated for positivity and freshness before provider use", async () => {
  const repo = await read("../../src/modules/pricing/repo/pricing.repo.ts");
  const service = await read("../../src/modules/pricing/service/pricing.service.ts");
  assert.match(repo, /from_currency[\s\S]*?to_currency/);
  assert.match(repo, /last_fetched[\s\S]*?(gt|gte|lt|lte)|asOf[\s\S]*?fresh|rate\s*>\s*0/i,
    "AI_PRICING_FX_RATE_STALE: Node returns currency rates without an age or positive-rate guard.");
  assert.match(service, /exchangeRates[\s\S]*?requestPricingRecommendation/);
});

test("Node evidence stores IDs and timestamps for the exact competitor observations used", async () => {
  const repo = await read("../../src/modules/pricing/repo/pricing.repo.ts");
  assert.match(repo, /source_record_ids:[\s\S]*?competitor_price|market_point|observation/i,
    "AI_PRICING_EVIDENCE_INCOMPLETE: Node evidence currently records product_id only, so an auditor cannot reproduce the selected market inputs.");
});

test("Node and FastAPI pricing use separate provider and persistence paths", async () => {
  const nodeClient = await read("../../src/modules/pricing/client/pricing.client.ts");
  const pythonMain = await read("../../../ai/src/ai/main.py");
  const pipeline = await read("../../../ai/src/ai/pricing/pipeline.py");
  assert.match(nodeClient, /service:\s*["']analytics["']/);
  assert.match(nodeClient, /apiName:\s*["']recommend["']/);
  assert.match(pythonMain, /@app\.post\(["']\/pricing\/recommend["']/);
  assert.match(pythonMain, /get_tenant_context/);
  assert.match(pipeline, /run_price_recommendation/);
  assert.match(pipeline, /insert_evidence_record/);
  assert.doesNotMatch(pythonMain, /incrementUsage|subscription_usage/);
});

test("FastAPI recommendation route derives product ownership from the authenticated tenant", async () => {
  const main = await read("../../../ai/src/ai/main.py");
  const start = main.indexOf("@app.post(\"/pricing/recommend\")");
  const route = main.slice(start, start + 900);
  assert.match(route, /ctx:\s*TenantContext\s*=\s*Depends\(get_tenant_context\)/);
  assert.match(route, /ctx\.tenant_id/);
  assert.match(route, /product_id/);
});

test("FastAPI and Node recommendation evidence retain source IDs only on the independent FastAPI path", async () => {
  const python = await read("../../../ai/src/ai/pricing/pipeline.py");
  const nodeRepo = await read("../../src/modules/pricing/repo/pricing.repo.ts");
  assert.match(python, /competitor_price_entry_ids.*rec\.source_record_ids/);
  assert.match(nodeRepo, /source_record_ids:\s*\{\s*product_id:/);
});

test("recommendation generation never updates the catalog selling price", async () => {
  const nodeService = await read("../../src/modules/pricing/service/pricing.service.ts");
  const nodeRepo = await read("../../src/modules/pricing/repo/pricing.repo.ts");
  const python = await read("../../../ai/src/ai/pricing/pipeline.py");
  assert.doesNotMatch(nodeService + nodeRepo, /products\.update|UPDATE\s+products/i);
  assert.doesNotMatch(python, /UPDATE\s+products|products\.current_price\s*=/i);
});

test("frontend sends only selected product ID and prevents overlapping submissions", async () => {
  const api = await read("../../../frontend/src/features/market-intelligence/api/pricingApi.js");
  const page = await read("../../../frontend/src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx");
  assert.match(api, /POST|\.post\(/);
  assert.match(api, /\/features\/pricing\/recommend/);
  assert.match(api, /product_id:\s*productId/);
  assert.match(page, /if\s*\(!selectedProductId\s*\|\|\s*pricingMutation\.isPending\)\s*return/);
  assert.match(page, /pricingByProduct/);
});

test("pricing UI explains remaining credits and checks feature availability before Generate", async () => {
  const page = await read("../../../frontend/src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx");
  assert.match(page, /ai_pricing|remaining.*(recommendation|credit)|recommendation.*(limit|credit)/i,
    "AI_PRICING_FALSE_SUCCESS_UI: page currently offers Generate/Refresh without verified ai_pricing entitlement or remaining-credit display.");
});

test("frontend recommendation is persisted across reloads rather than held only in component state", async () => {
  const page = await read("../../../frontend/src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx");
  assert.match(page, /GET.*pricing|pricing.*history|recommendation.*history/i,
    "AI_PRICING_FRONTEND_MISMATCH: generated recommendation is stored in local component state; no history retrieval is wired.");
});

test("AI Pricing action copy exists in English and Arabic and page uses translated keys", async () => {
  const english = JSON.parse(await read("../../../frontend/src/assets/locales/en.json"));
  const arabic = JSON.parse(await read("../../../frontend/src/assets/locales/ar.json"));
  const page = await read("../../../frontend/src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx");
  assert.equal(english.marketMain.actions.generateRecommendation, "Generate Recommendation");
  assert.equal(english.marketMain.actions.refreshRecommendation, "Refresh Recommendation");
  assert.equal(arabic.marketMain.actions.generateRecommendation, "إنشاء توصية");
  assert.equal(arabic.marketMain.actions.refreshRecommendation, "اعادة توصية");
  assert.match(page, /t\("marketMain\.actions\.generateRecommendation"\)/);
  assert.match(page, /t\("marketMain\.actions\.refreshRecommendation"\)/);
});

test("standard AI response contract requires bounded confidence and finite nonnegative prices", async () => {
  const client = await read("../../src/modules/pricing/client/pricing.client.ts");
  assert.match(client, /confidence_score:[\s\S]*?\.min\(0\)\.max\(1\)/);
  assert.match(client, /suggested_price:[\s\S]*?\.finite\(\)\.nonnegative\(\)/);
  assert.match(client, /status:\s*z\.literal\(["']UNKNOWN["']\)/);
});
