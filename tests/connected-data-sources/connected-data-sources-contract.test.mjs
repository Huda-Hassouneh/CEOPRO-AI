import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { hasRemainingCapacity } from "../../src/modules/features/service/entitlement-policy.ts";

const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
const catalog = read("src/modules/features/catalog.ts");
const plans = read("src/config/production-plans.ts");
const capacity = read("src/modules/features/service/capacity.service.ts");
const usage = read("src/modules/features/repo/usage.repo.ts");
const sourceService = read("src/modules/dataconnection/service/dataconnection.service.ts");
const sourceRepo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
const sourceRoute = read("src/modules/dataconnection/route/dataconnection.route.ts");
const sourceController = read("src/modules/dataconnection/controller/dataconnection.controller.ts");
const sourceTypes = read("src/modules/dataconnection/types/dataconnection.types.ts");
const sourceSchema = read("prisma/schema.prisma");
const baseline = read("prisma/migrations/20260800000000_baseline/migration.sql");
const aiJobManagement = read("../ai/src/ai/extraction/job_management.py");
const aiSourceRegistration = read("../ai/src/market_scraper/data_access.py");
const aiRoutes = read("../ai/src/ai/main.py");
const connectPage = read("../frontend/src/features/data-connections/pages/ConnectDataPage.jsx");
const connectApi = read("../frontend/src/features/data-connections/api/dataConnectionsApi.js");

test("catalog keeps access and capacity as separate lifetime features", () => {
  assert.match(catalog, /code: "data_integration"[\s\S]*?type: FeatureType\.boolean[\s\S]*?resetCycle: ResetCycle\.lifetime/);
  assert.match(catalog, /code: "connected_data_sources"[\s\S]*?type: FeatureType\.limit[\s\S]*?aggregationType: AggregationType\.max[\s\S]*?resetCycle: ResetCycle\.lifetime/);
  assert.match(capacity, /"connected_data_sources"/);
});

test("production Starter, Growth, and Enterprise capacities are 1, 5, and 20", () => {
  const plan = (code) => plans.match(new RegExp(`code: "${code}"[\\s\\S]*?features: \\[([\\s\\S]*?)\\]`))?.[1] ?? "";
  assert.match(plan("starter"), /limitFeature\("connected_data_sources", 1\)/);
  assert.match(plan("growth"), /limitFeature\("connected_data_sources", 5\)/);
  assert.match(plan("enterprise"), /limitFeature\("connected_data_sources", 20\)/);
});

test("the capacity decision uses a max ceiling and accepts only the last available slot", () => {
  assert.equal(hasRemainingCapacity({ currentUsage: 0, limit: 1 }), true);
  assert.equal(hasRemainingCapacity({ currentUsage: 1, limit: 1 }), false);
  assert.equal(hasRemainingCapacity({ currentUsage: 4, limit: 5 }), true);
  assert.equal(hasRemainingCapacity({ currentUsage: 5, limit: 5 }), false);
  assert.equal(hasRemainingCapacity({ currentUsage: 19, limit: 20 }), true);
  assert.equal(hasRemainingCapacity({ currentUsage: 20, limit: 20 }), false);
  assert.equal(hasRemainingCapacity({ currentUsage: 100, limit: null }), true);
});

test("authoritative connected-source usage is tenant-scoped and counts active rows", () => {
  const resolver = capacity.match(/case "connected_data_sources":([\s\S]*?)(?:case |default:)/)?.[1] ?? "";
  assert.match(resolver, /prisma\.data_sources\.count\(/);
  assert.match(resolver, /tenant_id: tenantId/);
  assert.match(resolver, /is_active: true/);
  assert.doesNotMatch(resolver, /created_at|period|monthly/i);
});

test("manual upload and non-connector source types do not consume persistent connector capacity", () => {
  const resolver = capacity.match(/case "connected_data_sources":([\s\S]*?)(?:case |default:)/)?.[1] ?? "";
  assert.match(resolver, /source_type:\s*\{\s*in:\s*\[[\s\S]*?"website"[\s\S]*?\]/,
    "SOURCE_TYPE_ACCOUNTING_MISMATCH: capacity usage currently counts every active data_sources row, including upload bookkeeping rows.");
});

test("unlimited custom MAX entitlement is supported without turning the feature into a monthly counter", () => {
  assert.match(usage, /if \(planFeature\.limit_value === null\)[\s\S]*?isUnlimited: true/);
  assert.match(usage, /feature\.resetCycle === "lifetime"[\s\S]*?subscriptionUsage\.findFirst/);
  assert.match(usage, /if \(entitlement\.isUnlimited\) return \{ allowed: true/);
});

test("active-source usage is independent of sync health and job status", () => {
  const resolver = capacity.match(/case "connected_data_sources":([\s\S]*?)(?:case |default:)/)?.[1] ?? "";
  assert.doesNotMatch(resolver, /ingestion_jobs|job_status|last_synced_at/);
});

test("manual Node uploads are inactive and excluded from persistent-source listings", () => {
  assert.match(sourceRepo, /source_type: "documents",\s*is_active: false/);
  assert.match(sourceRepo, /connectedSources[\s\S]*?where: \{[\s\S]*?is_active: true/);
  assert.match(sourceRepo, /source_type: \{\s*in: \[[\s\S]*?"website"[\s\S]*?\]\s*\}/);
});

test("registration applies the boolean entitlement at the route and numeric capacity in the service", () => {
  assert.match(sourceRoute, /router\.use\(authenticateUser, requireTenant\)/);
  assert.match(sourceRoute, /router\.post\([\s\S]*?"\/sources"[\s\S]*?requireEntitlement\("data_integration"\)/);
  assert.match(sourceService, /featureCode: "connected_data_sources"[\s\S]*?additionalAmount: 1/);
  assert.match(sourceService, /if \(!capacity\.allowed\)[\s\S]*?"USAGE_EXCEEDED"/);
  assert.match(sourceController, /const tenantId = req\.tenant_id/);
  assert.doesNotMatch(sourceController, /tenantId:\s*req\.body/);
});

test("Node source type allow-list matches its six public registration types", () => {
  for (const sourceType of ["shopify", "postgresql", "mysql", "sqlserver", "ga4", "website"]) {
    assert.match(sourceTypes, new RegExp(`"${sourceType}"`));
  }
  assert.doesNotMatch(sourceTypes, /"OWN_SYSTEM_CONNECTOR"/);
});

test("persistent source creation marks registration active but does not claim a verified connection", () => {
  const create = sourceRepo.match(/createPersistentSource: async[\s\S]*?\n  \},/)?.[0] ?? "";
  assert.match(create, /is_active: true/);
  assert.match(create, /connection_credentials_vault: null/);
  assert.match(create, /Active means configured, not that connection testing succeeded/);
  assert.match(sourceRepo, /dataStatus: "verified"/);
});

test("source lifecycle routes are not exposed yet, so activation/deactivation must remain blocked E2E cases", () => {
  assert.match(sourceRoute, /router\.post\([\s\S]*?"\/sources"/);
  assert.doesNotMatch(sourceRoute, /router\.(?:patch|put|delete)\(/);
});

test("database source rows carry tenant ownership and forced row-level security", () => {
  assert.match(sourceSchema, /model data_sources \{[\s\S]*?tenant_id\s+String\s+@db\.Uuid/);
  assert.match(baseline, /ALTER TABLE data_sources FORCE ROW LEVEL SECURITY/);
  assert.match(baseline, /CREATE POLICY isolation_data_sources ON data_sources FOR ALL USING \(tenant_id = get_current_tenant\(\)\)/);
});

test("regression: persistent source rows expose an update timestamp for lifecycle audit", () => {
  const model = sourceSchema.match(/model data_sources \{([\s\S]*?)\n\}/)?.[1] ?? "";
  assert.match(model, /updated_at/,
    "SOURCE_AUDIT_TIMESTAMP_MISSING: data_sources has created_at and last_synced_at but no updated_at field for lifecycle changes.");
});

test("duplicate source identity policy is not encoded as a unique key", () => {
  const model = sourceSchema.match(/model data_sources \{([\s\S]*?)\n\}/)?.[1] ?? "";
  assert.match(model, /@@unique\(\[tenant_id, source_id\]/);
  assert.doesNotMatch(model, /@@unique\(\[tenant_id, source_type|@@unique\(\[tenant_id, source_name/);
});

test("regression: capacity check and source insert must become one atomic operation", () => {
  const hasSharedAtomicBoundary = /(?:\$transaction|FOR UPDATE|advisory.*lock|serializable)/i.test(sourceService) &&
    /(?:capacity|connected_data_sources)[\s\S]{0,1200}(?:createPersistentSource|data_sources\.create)/i.test(sourceService);
  assert.ok(hasSharedAtomicBoundary,
    "SOURCE_LIMIT_RACE_CONDITION: service checks capacity before a separate repository insert; parallel requests can both claim the final slot.");
});

test("regression: AI manual-upload source rows must not consume persistent connector slots", () => {
  const insert = aiJobManagement.match(/INSERT INTO data_sources[\s\S]*?RETURNING source_id/)?.[0] ?? "";
  assert.match(insert, /is_active\s*,\s*FALSE|SET\s+is_active\s*=\s*FALSE/i,
    "AI_UPLOAD_COUNTS_AS_CONNECTION: AI upload source creation should explicitly set is_active=false.");
});

test("regression: AI-created active sources must enforce the same tenant capacity", () => {
  assert.match(aiRoutes, /@app\.post\("\/onboarding\/connect\/database"\)[\s\S]*?register_self_service_data_source/);
  assert.match(aiRoutes, /@app\.post\("\/onboarding\/connect\/api"\)[\s\S]*?register_self_service_data_source/);
  assert.match(aiSourceRegistration, /'OWN_SYSTEM_CONNECTOR'[\s\S]*?TRUE/);
  assert.match(aiRoutes + aiSourceRegistration, /connected_data_sources|assert.*capacity|reserve.*source/i,
    "AI_SOURCE_LIMIT_BYPASS: both AI onboarding endpoints call a direct active-source insert without the connected_data_sources entitlement.");
});

test("regression: source status must not label an unverified registration as verified", () => {
  assert.doesNotMatch(sourceRepo, /dataStatus:\s*"verified"/,
    "FALSE_SUCCESS_STATUS: overview maps source registration to dataStatus=verified without a connectivity check.");
});

test("regression: the connections UI must honor failed sync/reconnect results", () => {
  assert.match(connectPage, /result\.ok\s*===\s*false|if\s*\(!?result\.ok\)/,
    "FALSE_SUCCESS_UI: ConnectDataPage shows a success notice after sync() resolves {ok:false}.");
  assert.match(connectApi, /sync:\s*\(sourceId\)\s*=>\s*previewDelay\(\{\s*ok:\s*false/);
});

test("regression: the connections UI must display the entitlement limit and remaining capacity", () => {
  assert.match(connectPage, /(?:remainingCapacity|sourceLimit|quota|source.{0,20}limit)/i,
    "QUOTA_DISPLAY_MISSING: current page displays a source count but not its effective limit or remaining slots.");
});

test("regression: website registration must preserve and validate its submitted URL", () => {
  assert.match(sourceService, /sourceUrl|source_url|payload\.url/,
    "CONNECTOR_CONFIGURATION_MISMATCH: frontend sends url, but backend currently persists metadata only and drops it.");
});
