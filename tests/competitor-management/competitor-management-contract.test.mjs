import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (file) => readFileSync(new URL(`../../${file}`, import.meta.url), "utf8");

test("competitor management UI uses preview-only Add Competitor submission", () => {
  const page = read("../frontend/src/features/market-intelligence/pages/AddCompetitorPage.jsx");
  const api = read("../frontend/src/features/market-intelligence/api/competitorsApi.js");
  const listPage = read("../frontend/src/features/market-intelligence/pages/CompetitorsPage.jsx");
  assert.match(page, /addPreviewCompetitor\(values\)/);
  assert.doesNotMatch(page, /useAddCompetitor|competitorsApi\.create/);
  assert.match(api, /httpClient\.post\(`\/competitors`, payload\)/);
  assert.match(listPage, /useCompetitors\(\)/);
  assert.match(listPage, /<select[\s\S]*?value=\{industry\}/);
  assert.match(listPage, /<Button variant="outline" leadingIcon=\{<Filter/);
});

test("competitor API has authenticated tenant list/create/profile routes but no lifecycle endpoints", () => {
  const route = read("src/modules/competitors/route/competitors.route.ts");
  const app = read("src/app.ts");
  assert.match(route, /router\.use\(authenticateUser, requireTenant\)/);
  assert.match(app, /app\.use\("\/competitors", competitors\)/);
  assert.match(route, /router\.get\("\/",/);
  assert.match(route, /router\.post\("\/",/);
  assert.match(route, /router\.get\("\/:competitorId",/);
  assert.doesNotMatch(route, /router\.(?:put|patch|delete)\(/);
});

test("backend create validation is name-only and does not enforce feature access or tracked capacity", () => {
  const service = read("src/modules/competitors/service/competitors.service.ts");
  const controller = read("src/modules/competitors/controller/competitors.controller.ts");
  const repository = read("src/modules/competitors/repo/competitors.repo.ts");
  assert.match(service, /if \(!payload\.name\) throw new Error/);
  assert.doesNotMatch(service, /competitor_management|tracked_competitors|assertFeatureCapacity|assertFeatureAccess/);
  assert.match(controller, /createCompetitor\(tenantId, req\.body\)/);
  assert.match(repository, /tenant_competitors\.upsert/);
  assert.doesNotMatch(repository, /assertFeatureCapacity|tracked_competitors/);
});

test("manual competitor identity is exact name matching; tenant relationship upsert reactivates tracking", () => {
  const repository = read("src/modules/competitors/repo/competitors.repo.ts");
  const create = repository.match(/export const createCompetitor = async[\s\S]*?\n\};/)?.[0] ?? "";
  assert.match(create, /global_competitors\.findFirst\(\{\s*where: \{ competitor_name: data\.name \}/);
  assert.doesNotMatch(create, /website_identity_key/);
  assert.match(create, /if \(!globalComp\)[\s\S]*?website_url: data\.website/);
  assert.match(repository, /update: \{ is_tracked: true \}/);
  assert.match(repository, /create: \{[\s\S]*?is_tracked: true/);
});

test("Growth and Enterprise catalog settings are 10/24h and 50/6h", () => {
  const plans = read("src/config/production-plans.ts");
  assert.match(plans, /booleanFeature\("competitor_management", competitorMonitoringMetadata\(1_440,/);
  assert.match(plans, /limitFeature\("tracked_competitors", 10\)/);
  assert.match(plans, /booleanFeature\("competitor_management", competitorMonitoringMetadata\(360,/);
  assert.match(plans, /limitFeature\("tracked_competitors", 50\)/);
});

test("tenant relations, mappings, and prices have composite tenant ownership and forced RLS", () => {
  const schema = read("prisma/schema.prisma");
  const migration = read("prisma/migrations/20260800000000_baseline/migration.sql");
  assert.match(schema, /model tenant_competitors \{[\s\S]*?@@id\(\[tenant_id, global_competitor_id\]/);
  assert.match(schema, /model competitor_product_mappings \{[\s\S]*?@@unique\(\[tenant_id, global_competitor_id, product_id\]/);
  assert.match(schema, /model competitor_prices \{[\s\S]*?source_status\s+String/);
  for (const table of ["tenant_competitors", "global_competitors", "competitor_product_mappings", "competitor_prices"]) {
    assert.match(migration, new RegExp(`ALTER TABLE ${table} FORCE ROW LEVEL SECURITY`));
  }
  assert.match(migration, /CREATE POLICY isolation_tenant_competitors ON tenant_competitors FOR ALL USING \(tenant_id = get_current_tenant\(\)\)/);
  assert.match(migration, /CREATE POLICY isolation_mappings ON competitor_product_mappings FOR ALL USING \(tenant_id = get_current_tenant\(\)\)/);
  assert.match(migration, /CREATE POLICY isolation_competitor_prices ON competitor_prices FOR ALL USING \(tenant_id = get_current_tenant\(\)\)/);
});

test("profile reports latest available price and change activity without FX or freshness policy", () => {
  const repository = read("src/modules/competitors/repo/competitors.repo.ts");
  const profile = repository.match(/export const getCompetitorProfile = async[\s\S]*?\n\};/)?.[0] ?? "";
  assert.match(profile, /where: \{ is_available: true \}/);
  assert.match(profile, /orderBy: \{ observed_at: "desc" \}/);
  assert.match(profile, /if \(current !== previous\)/);
  assert.match(profile, /competitorPrice: Number\(prices\[0\]\.scraped_price\)/);
  assert.doesNotMatch(profile, /currency_rates|exchange_rate|stale|freshness|source_status/);
  assert.match(profile, /metrics: \[\]/);
});

test("normal AI upload publishes discovery and worker gates collection on already ALLOWED sources", () => {
  const main = read("../ai/src/ai/main.py");
  const worker = read("../ai/src/market_scraper/discovery_worker.py");
  const nodeUpload = read("src/modules/dataconnection/controller/dataconnection.controller.ts");
  assert.match(main, /promotion\.promote_ingested_rows/);
  assert.match(main, /if promotion_summary\.products_created > 0:[\s\S]*?_publish_discovery_request\(ctx\.tenant_id\)/);
  assert.match(worker, /DISCOVERY_STREAM_KEY.*market\.discovery\.requested/);
  assert.match(worker, /discover_competitors_for_tenant/);
  assert.match(worker, /policy_status.*ALLOWED/);
  assert.doesNotMatch(nodeUpload, /market\.discovery\.requested|publish_discovery/);
});
