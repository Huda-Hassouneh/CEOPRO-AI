import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { hasRemainingCapacity } from "../../src/modules/features/service/entitlement-policy.ts";

const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
const catalog = read("src/modules/features/catalog.ts");
const plans = read("src/config/production-plans.ts");
const capacity = read("src/modules/features/service/capacity.service.ts");
const sourceTypePolicy = read("src/constants/data-source-types.ts");
const usage = read("src/modules/features/repo/usage.repo.ts");
const sourceService = read("src/modules/dataconnection/service/dataconnection.service.ts");
const sourceRepo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
const sourceRoute = read("src/modules/dataconnection/route/dataconnection.route.ts");
const sourceController = read("src/modules/dataconnection/controller/dataconnection.controller.ts");
const sourceTypes = read("src/modules/dataconnection/types/dataconnection.types.ts");
const sourceValidation = read("src/modules/dataconnection/types/dataconnection.validation.ts");
const sourceSchema = read("prisma/schema.prisma");
const baseline = read("prisma/migrations/20260800000000_baseline/migration.sql");
const connectPage = read("../frontend/src/features/data-connections/pages/ConnectDataPage.jsx");
const connectApi = read("../frontend/src/features/data-connections/api/dataConnectionsApi.js");
const capacityMigration = read("prisma/migrations/20261012000000_enforce_connected_source_capacity/migration.sql");

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
  assert.match(resolver, /COUNTED_CONNECTED_SOURCE_TYPES/);
  assert.doesNotMatch(resolver, /created_at|period|monthly/i);
});

test("manual upload and non-connector source types do not consume persistent connector capacity", () => {
  const resolver = capacity.match(/case "connected_data_sources":([\s\S]*?)(?:case |default:)/)?.[1] ?? "";
  assert.match(resolver, /source_type:\s*\{\s*in:\s*\[\.\.\.COUNTED_CONNECTED_SOURCE_TYPES\]\s*\}/);
  assert.match(sourceTypePolicy, /"website"[\s\S]*?"OWN_SYSTEM_CONNECTOR"/);
  assert.doesNotMatch(sourceTypePolicy, /"documents"/,
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

test("manual Node uploads are inactive and persistent source lists include only connector kinds", () => {
  assert.match(sourceRepo, /source_type: "documents",\s*is_active: false/);
  assert.match(sourceRepo, /connectedSources[\s\S]*?source_type: \{ in: \[\.\.\.PERSISTENT_SOURCE_TYPES\] \}/);
  assert.match(sourceRepo, /const PERSISTENT_SOURCE_TYPES = COUNTED_CONNECTED_SOURCE_TYPES/);
  assert.match(sourceTypePolicy, /PERSISTENT_DATA_SOURCE_TYPES[\s\S]*?"website"/);
});

test("registration applies the boolean entitlement at the route and numeric capacity in the service", () => {
  assert.match(sourceRoute, /router\.use\(authenticateUser, requireTenant\)/);
  assert.match(sourceRoute, /router\.post\([\s\S]*?"\/sources"[\s\S]*?requireEntitlement\("data_integration"\)/);
  assert.match(sourceRepo, /getConnectedDataSourceCapacityInTransaction[\s\S]*?createPersistentSource/);
  assert.match(sourceRepo, /pg_advisory_xact_lock/);
  assert.match(sourceRepo, /ConnectedSourceCapacityError/);
  assert.match(sourceController, /const tenantId = req\.tenant_id/);
  assert.doesNotMatch(sourceController, /tenantId:\s*req\.body/);
});

test("Node source type allow-list matches its six public registration types", () => {
  for (const sourceType of ["shopify", "postgresql", "mysql", "sqlserver", "ga4", "website"]) {
    assert.match(sourceTypePolicy, new RegExp(`"${sourceType}"`));
  }
  assert.doesNotMatch(sourceTypePolicy.match(/PERSISTENT_DATA_SOURCE_TYPES = Object\.freeze\(\[([\s\S]*?)\]\)/)?.[1] ?? "", /"OWN_SYSTEM_CONNECTOR"/);
  assert.match(sourceValidation, /normalizeSourceUrl\(value\.sourceUrl \?\? value\.url\)/);
});

test("persistent source creation saves configuration and never claims verification", () => {
  const create = sourceRepo.match(/createPersistentSource: async[\s\S]*?\n  \},/)?.[0] ?? "";
  assert.match(create, /is_active: true/);
  assert.match(create, /connection_credentials_vault: null/);
  assert.match(create, /Active means configured, not that connection testing succeeded/);
  assert.match(create, /source_url: input\.sourceUrl/);
  assert.doesNotMatch(sourceRepo, /dataStatus:\s*"verified"/);
  assert.match(sourceService, /"configured"/);
});

test("source pause and reactivation are authenticated and reactivation rechecks capacity", () => {
  assert.match(sourceRoute, /router\.patch\([\s\S]*?"\/sources\/:sourceId"/);
  assert.match(sourceRepo, /setPersistentSourceActive:[\s\S]*?getConnectedDataSourceCapacityInTransaction/);
  assert.match(sourceRepo, /data: \{ is_active: input\.isActive \}/);
});

test("disconnect removes vaulted credentials, releases capacity, and retains source history", () => {
  assert.match(sourceRoute, /router\.delete\([\s\S]*?"\/sources\/:sourceId\/connection"/);
  assert.match(sourceRepo, /disconnectPersistentSource:[\s\S]*?connection_credentials_vault: null/);
  assert.match(sourceRepo, /ceopro_connection_status: "disconnected"/);
  assert.match(sourceRepo, /is_active: false/);
  assert.match(sourceRepo, /source_id: source\.source_id/);
  assert.match(sourceService, /connectionStatus: "disconnected"/);
  assert.match(sourceRepo, /DataSourceReconnectRequiredError/);
});

test("capacity summary reports real usage when an entitlement is missing and exposes downgrade excess", () => {
  assert.match(usage, /const currentUsage = await tx\.data_sources\.count/);
  assert.match(usage, /getFeatureAccessInfo\(tenantId, "data_integration", tx\)/);
  assert.match(usage, /included: false as const,[\s\S]*?currentUsage,[\s\S]*?isOverLimit: currentUsage > limit/);
  assert.match(usage, /isOverLimit: limit !== null && currentUsage > limit/);
});

test("existing sources remain readable and disconnectable after data_integration is removed", () => {
  assert.match(sourceRoute, /router\.get\([\s\S]*?"\/"[\s\S]*?getConnectionsOverview/);
  assert.match(sourceRoute, /router\.delete\([\s\S]*?"\/sources\/:sourceId\/connection"[\s\S]*?disconnectSource/);
  assert.match(sourceRoute, /router\.post\([\s\S]*?"\/sources"[\s\S]*?requireEntitlement\("data_integration"\)/);
  assert.match(sourceRoute, /router\.post\([\s\S]*?requireEntitlement\("document_extraction"\)[\s\S]*?uploadFile/);
  assert.doesNotMatch(sourceRoute.match(/router\.patch\([\s\S]*?"\/sources\/:sourceId"[\s\S]*?\);/)?.[0] ?? "", /requireEntitlement/);
});

test("database source rows carry tenant ownership and forced row-level security", () => {
  assert.match(sourceSchema, /model data_sources \{[\s\S]*?tenant_id\s+String\s+@db\.Uuid/);
  assert.match(baseline, /ALTER TABLE data_sources FORCE ROW LEVEL SECURITY/);
  assert.match(baseline, /CREATE POLICY isolation_data_sources ON data_sources FOR ALL USING \(tenant_id = get_current_tenant\(\)\)/);
});

test("source lifecycle uses existing schema fields and does not add a migration", () => {
  const model = sourceSchema.match(/model data_sources \{([\s\S]*?)\n\}/)?.[1] ?? "";
  assert.match(model, /is_active\s+Boolean/);
  assert.doesNotMatch(model, /updated_at/);
});

test("source duplicates are blocked under a tenant-scoped lock without a schema migration", () => {
  const model = sourceSchema.match(/model data_sources \{([\s\S]*?)\n\}/)?.[1] ?? "";
  assert.doesNotMatch(model, /@@unique\(\[tenant_id, source_type|@@unique\(\[tenant_id, source_name/);
  assert.match(sourceRepo, /pg_advisory_xact_lock/);
  assert.match(sourceRepo, /DuplicateDataSourceError/);
  assert.match(sourceRepo, /source_url: input\.sourceUrl/);
});

test("source capacity check and insert share one tenant-locked transaction", () => {
  const create = sourceRepo.match(/createPersistentSource: async[\s\S]*?\n  setPersistentSourceActive/)?.[0] ?? "";
  assert.match(create, /withTenantContext[\s\S]*?pg_advisory_xact_lock/);
  assert.match(create, /\$executeRawUnsafe\([\s\S]*?pg_advisory_xact_lock/);
  assert.doesNotMatch(create, /\$queryRawUnsafe\([\s\S]*?pg_advisory_xact_lock/);
  assert.match(create, /getConnectedDataSourceCapacityInTransaction[\s\S]*?tx\.data_sources\.create/);
});

test("source reactivation uses executeRaw for the void-returning advisory lock", () => {
  const reactivate = sourceRepo.match(/setPersistentSourceActive: async[\s\S]*?\n  countActivePersistentSources:/)?.[0] ?? "";
  assert.ok(reactivate, "source reactivation repository method must exist");
  assert.match(reactivate, /\$executeRawUnsafe\([\s\S]*?pg_advisory_xact_lock/);
  assert.doesNotMatch(reactivate, /\$queryRawUnsafe\([\s\S]*?pg_advisory_xact_lock/);
});

test("manual-upload source types do not count toward connected-source capacity", () => {
  assert.match(sourceTypePolicy, /COUNTED_CONNECTED_SOURCE_TYPES/);
  assert.doesNotMatch(sourceTypePolicy, /"documents"/);
});

test("database quota trigger protects direct AI connector writes without reading or editing AI source", () => {
  assert.match(capacityMigration, /BEFORE INSERT OR UPDATE/);
  assert.match(capacityMigration, /pg_advisory_xact_lock/);
  assert.match(capacityMigration, /connected_data_sources/);
  assert.match(capacityMigration, /data_integration/);
  assert.match(capacityMigration, /OWN_SYSTEM_CONNECTOR/);
});

test("regression: source status must not label an unverified registration as verified", () => {
  assert.doesNotMatch(sourceRepo, /dataStatus:\s*"verified"/,
    "FALSE_SUCCESS_STATUS: overview maps source registration to dataStatus=verified without a connectivity check.");
});

test("the connections UI exposes no preview sync or reconnect action", () => {
  assert.doesNotMatch(connectApi, /previewDelay|connectGoogleAnalytics|prepareDatabase|reconnect|sync:/);
  assert.match(connectPage, /type !== "website"/);
  assert.match(connectPage, /sourceConfigured/);
  assert.match(connectPage, /dataConnectionsApi\.setActive/);
  assert.match(connectApi, /disconnect: async/);
});

test("regression: the connections UI must display the entitlement limit and remaining capacity", () => {
  assert.match(connectPage, /(?:remainingCapacity|sourceLimit|quota|source.{0,20}limit)/i,
    "QUOTA_DISPLAY_MISSING: current page displays a source count but not its effective limit or remaining slots.");
});

test("regression: website registration must preserve and validate its submitted URL", () => {
  assert.match(sourceService, /sourceUrl|source_url|payload\.url/,
    "CONNECTOR_CONFIGURATION_MISMATCH: frontend sends url, but backend currently persists metadata only and drops it.");
  assert.match(sourceRepo, /source_url: input\.sourceUrl/);
  assert.match(connectApi, /sourceUrl: url/);
});
