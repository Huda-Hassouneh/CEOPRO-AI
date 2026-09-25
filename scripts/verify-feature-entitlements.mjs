import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const pkg = JSON.parse(read("package.json"));
const catalog = read("src/modules/features/catalog.ts");
const usage = read("src/modules/features/repo/usage.repo.ts");
const validator = read("src/validators/validateFeatures.ts");
const routes = read("src/modules/features/routes/features.route.ts");
const featureIndex = read("src/modules/features/index.ts");
const bootstrap = read("prisma/bootstrap-features.ts");

assert.equal(pkg.scripts["bootstrap:features"], "tsx prisma/bootstrap-features.ts");
assert.match(bootstrap, /ALLOW_PRODUCTION_FEATURE_BOOTSTRAP/);
assert.match(bootstrap, /customPlanQuoteFeature/);
assert.match(bootstrap, /vendorRate/);
assert.match(bootstrap, /subscriptionUsage/);
assert.match(usage, /aggregationType === "max"/);
assert.match(usage, /getCurrentCapacityUsage/);
assert.match(usage, /cannot be incremented/);
assert.match(validator, /requireFeatureAccess/);
assert.match(validator, /QUOTA_EXHAUSTED|blockReason/);
assert.match(featureIndex, /router\.use\("\/features", featureOperationRoutes\)/);
assert.match(routes, /requireFeatureAccess\("sentiment_analysis"\)/);
assert.match(routes, /requireEntitlement\("rag_assistant"\)/);

const codes = [
  "dashboard_analytics", "market_intelligence", "market_perception",
  "demand_prediction", "inventory_intelligence", "product_management",
  "competitor_management", "data_integration", "business_recommendations",
  "system_alerts", "ai_pricing", "sentiment_analysis", "rag_assistant",
  "document_extraction", "report_generation", "marketing_image_generation",
  "tracked_competitors", "tracked_products", "connected_data_sources",
  "team_members", "document_storage_gb"
];
for (const code of codes) assert.match(catalog, new RegExp(`code: "${code}"`));
console.log("Feature entitlement source-contract verification passed.");
