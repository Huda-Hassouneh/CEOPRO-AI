import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = process.cwd();
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const withoutComments = (source) => source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

test("Market Intelligence is exposed in the UI only behind its catalog feature guard", () => {
  const router = read("../frontend/src/app/router/index.jsx");
  assert.match(router, /FeatureRouteGuard featureCodes="market_intelligence"[\s\S]*?MarketIntelligenceOverviewPage/);
  const catalog = read("src/modules/features/types/feature.catalog.ts");
  assert.match(catalog, /code:\s*"market_intelligence"/);
  const plans = read("src/config/production-plans.ts");
  assert.match(plans, /code:\s*"growth"[\s\S]*?booleanFeature\("market_intelligence"\)/i);
  assert.match(plans, /code:\s*"enterprise"[\s\S]*?booleanFeature\("market_intelligence"\)/i);
});

test("Market Intelligence backend route authenticates and enforces the feature entitlement", () => {
  const route = read("src/modules/market-intelligence/route/market-int.route.ts");
  assert.match(route, /authenticateUser/);
  assert.match(route, /requireTenant/);
  assert.ok(/requireEntitlement\(["']market_intelligence["']\)/.test(route), "Missing requireEntitlement(\"market_intelligence\") on the authenticated backend route.");
});

test("generated AI pricing recommendations enforce their separate ai_pricing entitlement", () => {
  const route = read("src/modules/pricing/route/pricing.route.ts");
  assert.ok(/requireEntitlement\(["']ai_pricing["']\)[,\s\n]*recommendPrice/.test(withoutComments(route)), "Missing active requireEntitlement(\"ai_pricing\") middleware on POST /features/pricing/recommend.");
});

test("Market Perception enrichment exposed on the overview requires market_perception access", () => {
  const service = read("src/modules/market-intelligence/service/market-int.service.ts");
  assert.match(service, /getMpiSummary/);
  assert.ok(/requireFeatureAccess|requireEntitlement|hasFeatureAccess|checkFeatureAccess/.test(service), "Overview calls MPI enrichment without checking the separate market_perception entitlement.");
});

test("standalone MPI endpoint enforces market_perception access", () => {
  const mpiRoute = read("src/modules/mpi/route/mpi.route.ts");
  assert.ok(/requireFeatureAccess\(["']market_perception["']\)[,\s\n]*getSummary/.test(withoutComments(mpiRoute)), "The standalone MPI route has its market_perception entitlement middleware commented out.");
});

test("Overview score units and pricing recommendation trigger match the current UI and API", () => {
  const repo = read("src/modules/market-intelligence/repo/market-int.repo.ts");
  assert.match(repo, /calculatePricingScore/);
  assert.match(repo, /averageCompositeScore100/);
  assert.match(repo, /score10/);
  assert.match(repo, /score100/);
  const page = read("../frontend/src/features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx");
  assert.match(page, /metric\.format === "score100"/);
  assert.match(page, /metric\.format === "score10"/);
  assert.match(page, /exportMarketIntelligencePdf/);
  const api = read("../frontend/src/features/market-intelligence/api/marketIntelligenceApi.js");
  assert.match(api, /POST|post\(/);
  assert.match(api, /\/features\/pricing\/recommend/);
  const pricingRoute = read("src/modules/pricing/route/pricing.route.ts");
  assert.match(pricingRoute, /requireEntitlement\("ai_pricing"\)/);
  assert.match(pricingRoute, /\/recommend/);
});


test("overview validates requested products and scopes its reads to a tenant RLS transaction", () => {
  const route = read("src/modules/market-intelligence/route/market-int.route.ts");
  assert.match(route, /validateMarketOverviewQuery/);
  const repo = read("src/modules/market-intelligence/repo/market-int.repo.ts");
  assert.match(repo, /app.current_tenant_id/);
  assert.match(repo, /app.current_user_id/);
  assert.match(repo, /RepeatableRead/);
  assert.match(repo, /summarizeMarketDemand/);
  assert.match(repo, /distinct:\s*\["currency"\]/);
});
