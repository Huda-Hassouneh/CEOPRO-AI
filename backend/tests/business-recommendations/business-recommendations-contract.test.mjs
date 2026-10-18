import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const featureCatalog = read("../../src/modules/features/types/feature.catalog.ts");
const plans = read("../../src/config/production-plans.ts");
const entitlement = read("../../src/modules/features/service/features.service.ts");
const routes = read("../../src/app.ts");
const dashboardRoute = read("../../src/modules/dashboard/route/dashboard.route.ts");
const aiMain = read("../../../ai/src/ai/main.py");
const aiDatabase = read("../../../ai/src/ai/db.py");
const aiResponse = read("../../../ai/src/ai/dashboard/recommendations.py");
const dashboardHome = read("../../../frontend/src/features/dashboard/pages/DashboardHomePage.jsx");
const recommendationCard = read("../../../frontend/src/features/dashboard/components/RecommendationCard.jsx");
test("canonical catalog defines business_recommendations as a lifetime boolean access feature", () => {
  const block = featureCatalog.match(/\{[\s\S]*?code:\s*"business_recommendations"[\s\S]*?\n\s*\},/)?.[0] ?? "";
  assert.match(block, /type:\s*FeatureType\.boolean/);
  assert.match(block, /resetCycle:\s*ResetCycle\.lifetime/);
});

test("Starter, Growth, and Enterprise do not grant business_recommendations", () => {
  for (const code of ["starter", "growth", "enterprise"]) {
    const plan = plans.match(new RegExp(`code: "${code}"[\\s\\S]*?features: \\[([\\s\\S]*?)\\]`))?.[1] ?? "";
    assert.ok(plan, `production plan ${code} was not found`);
    assert.doesNotMatch(plan, /business_recommendations/);
  }
});

test("central entitlement infrastructure can resolve custom plan feature grants", () => {
  assert.match(entitlement, /getRemainingUsage|checkFeatureAccess|feature\.code/);
});

test("Node-facing Python API requires a valid Node session and bounds its result",()=>{
 const api=read("../../../ai/src/ai/insights/api.py");
 assert.match(api,/ge=1,le=500/);assert.match(api,/node_context/);assert.match(api,/auth_sessions/);
 assert.match(api,/db.app_role_connection/);
});

test("AI response is currently limited to product, category, priority, and message", () => {
  assert.match(aiResponse, /"product_id": insight\.product_id/);
  assert.match(aiResponse, /"category": _CATEGORY_LABELS/);
  assert.match(aiResponse, /"priority": _priority_label/);
  assert.match(aiResponse, /"message": insight\.message/);
  assert.doesNotMatch(aiResponse, /evidence|as_of|recommendation_id|source_records/);
});

test("Node exposes a dedicated business recommendations route", () => {
  assert.match(routes, /features\/business-recommendations/);
  const route=read("../../src/modules/business-recommendations/route.ts");
  assert.match(route,/requireFeatureAccess\('business_recommendations'\)/);
  assert.match(route,/authenticateUser,requireTenant/);
});

test("dashboard recommendation card is static and not rendered by DashboardHomePage", () => {
  assert.match(recommendationCard, /t\('dashboard\.recommendation\.headline'\)/);
  assert.doesNotMatch(dashboardHome, /RecommendationCard|dashboard\.recommendation/);
});

test("business API validates a current Node session and explicit feature grant",()=>{
 const api=read("../../../ai/src/ai/insights/api.py");
 assert.match(api,/auth_sessions/);assert.match(api,/revoked_at IS NULL/);assert.match(api,/hmac.compare_digest/);
 const route=read("../../src/modules/business-recommendations/route.ts");assert.match(route,/requireFeatureAccess/);
});
