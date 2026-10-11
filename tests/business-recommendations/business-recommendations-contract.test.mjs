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

test("AI endpoint is tenant-token protected and bounds the recommendation limit", () => {
  const endpoint = aiMain.match(/@app\.get\("\/dashboard\/recommendations"\)[\s\S]*?(?=\n\n@app\.)/)?.[0] ?? "";
  assert.match(endpoint, /limit:[\s\S]*?ge=1[\s\S]*?le=20/);
  assert.match(endpoint, /Depends\(get_tenant_context\)/);
  assert.match(endpoint, /ctx\.tenant_id/);
  assert.match(endpoint, /db\.app_role_connection\(ctx\.tenant_id, ctx\.user_id\)/);
  assert.match(endpoint, /return \{"recommendations": result\}/);
  assert.match(aiDatabase, /SET LOCAL|set_config\('app\.current_tenant_id'/);
});

test("AI response is currently limited to product, category, priority, and message", () => {
  assert.match(aiResponse, /"product_id": insight\.product_id/);
  assert.match(aiResponse, /"category": _CATEGORY_LABELS/);
  assert.match(aiResponse, /"priority": _priority_label/);
  assert.match(aiResponse, /"message": insight\.message/);
  assert.doesNotMatch(aiResponse, /evidence|as_of|recommendation_id|source_records/);
});

test("Node has no customer-facing recommendation proxy or entitlement-gated route", () => {
  assert.doesNotMatch(routes, /business.?recommendations|dashboard\/recommendations/i);
  assert.doesNotMatch(dashboardRoute, /recommendation/i);
});

test("dashboard recommendation card is static and not rendered by DashboardHomePage", () => {
  assert.match(recommendationCard, /t\('dashboard\.recommendation\.headline'\)/);
  assert.doesNotMatch(dashboardHome, /RecommendationCard|dashboard\.recommendation/);
});

test("source audit records that custom-plan/API/frontend E2E cannot be inferred from AI JWT auth", () => {
  assert.match(aiMain, /get_tenant_context/);
  assert.doesNotMatch(aiMain, /business_recommendations|requireEntitlement/);
  assert.doesNotMatch(routes, /business_recommendations|dashboard\/recommendations/i);
});
