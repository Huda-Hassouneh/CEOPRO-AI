import { test } from "@playwright/test";

const tenantId = process.env.COMPETITOR_TEST_TENANT_ID;

function blocked(testInfo: Parameters<typeof test>[1] extends (...args: never[]) => unknown ? never : any, category: string, expected: string, actual: string, tables: string, owner: string) {
  testInfo.annotations.push({ type: "mode", description: "competitor-management-deterministic-e2e" });
  testInfo.annotations.push({ type: "failure-category", description: category });
  testInfo.annotations.push({ type: "tenant", description: tenantId || "not configured" });
  testInfo.annotations.push({ type: "database-tables", description: tables });
  testInfo.annotations.push({ type: "expected", description: expected });
  testInfo.annotations.push({ type: "actual", description: actual });
  testInfo.annotations.push({ type: "responsible", description: owner });
  testInfo.skip(true, `BLOCKED: no verified disposable competitor test DB, tenant identities, or safe fixture cleanup is configured. ${actual}`);
}

const cases: Array<[string, string, string, string, string, string]> = [
  ["owner creates competitor and it persists after reload", "COMPETITOR_NOT_PERSISTED", "POST returns a durable ID and tenant list still contains it after reload", "Add Competitor submits addPreviewCompetitor(values); no backend request is sent from the form.", "global_competitors, tenant_competitors", "Frontend API integration"],
  ["backend creation validates required name and website", "COMPETITOR_NOT_PERSISTED", "Malformed/missing required fields return a client error", "Backend service validates name only; website is optional and URL validation is frontend-only.", "global_competitors", "Backend validation"],
  ["duplicate requests reuse a canonical identity without conflicts", "COMPETITOR_IDENTITY_CONFLICT", "Normalized business identity is reused without merging distinct businesses", "Node path matches exact competitor_name; it does not normalize name/website and ignores submitted website on global match.", "global_competitors, tenant_competitors", "Identity policy across Node and AI"],
  ["tenants share global identity without exposing private tracking or mappings", "CROSS_TENANT_DATA_EXPOSURE", "Tenant A cannot list or profile Tenant B relationships, mappings, or observations", "RLS and tenant-scoped relation queries exist; runtime role and actual two-tenant database behavior are unverified.", "tenant_competitors, competitor_product_mappings, competitor_prices", "RLS/runtime role verification"],
  ["Growth plan denies access and enforces a 10 competitor limit", "COMPETITOR_LIMIT_BYPASS", "Server rejects access-disabled plan and the 11th concurrent tracked competitor", "Catalog declares 10 and 24h; competitor API has no feature or tracked-capacity check.", "tenant_competitors, feature_assignments, subscriptions", "Backend entitlement and capacity enforcement"],
  ["Enterprise plan enforces a 50 competitor limit", "COMPETITOR_LIMIT_BYPASS", "Server rejects the 51st tracked competitor", "Catalog declares 50 and 6h; competitor API has no tracked-capacity check.", "tenant_competitors, feature_assignments, subscriptions", "Backend capacity enforcement"],
  ["custom plan limits and concurrent additions are enforced atomically", "COMPETITOR_LIMIT_BYPASS", "Configured custom ceiling cannot be exceeded by concurrent or repeated requests", "No competitor write-path capacity assertion or atomic quota transaction was found.", "tenant_competitors, feature_assignments", "Backend transactional capacity enforcement"],
  ["untrack, reactivate and edit preserve observations", "COMPETITOR_TRACKING_STATE_ERROR", "Lifecycle endpoints change tenant link state without deleting historical prices", "Only list, create and profile routes exist; there are no update, untrack or reactivate routes.", "tenant_competitors, competitor_prices, market_observations", "Backend lifecycle API"],
  ["profile denies unknown and foreign-tenant competitor IDs", "CROSS_TENANT_DATA_EXPOSURE", "Foreign or unknown IDs reveal no profile or existence details", "Repository scopes profile by tenant link; actual HTTP status and RLS denial need two-tenant integration evidence.", "tenant_competitors, competitor_product_mappings", "Backend authorization and RLS"],
  ["profile price comparison handles currencies, stale values and blocked sources", "CURRENCY_MISMATCH", "Only fresh eligible same-currency comparisons are presented as current", "Profile exposes latest available saved price/currency; no conversion, freshness threshold, or source_status filtering is applied here.", "competitor_prices, competitor_product_mappings, products, data_sources", "Pricing/freshness policy"],
  ["price change history derives adjacent observations in correct order", "PRICE_COMPARISON_ERROR", "Activity reflects ordered consecutive observations and valid price changes", "Repository compares numeric prices ordered by observed_at; ties have no secondary ordering key.", "competitor_prices, competitor_product_mappings", "Observation ordering contract"],
  ["product mappings are tenant-owned and unique per product and competitor", "PRODUCT_MAPPING_ERROR", "Mapping references correct tenant/product and competitor and is not misleading", "Schema has composite tenant FK/unique identity; no exactness or package-size validation is performed in this API.", "competitor_product_mappings, products", "Mapping producer and validation"],
  ["industry and action filters work on backend-derived competitor rows", "FRONTEND_PLACEHOLDER", "Only industries present in returned data are selectable and filter actions have behavior", "Industry select is hard-coded; adjacent Filter button has no handler.", "N/A", "Frontend controls"],
  ["normal product ingestion triggers candidate discovery and approved collection only", "DISCOVERY_TRIGGER_MISSING", "Production upload event reaches discovery worker; only previously ALLOWED sources enqueue collection", "AI FastAPI extraction path publishes market.discovery.requested after created products; Node hosted extraction path has no such event in its controller.", "products, tenant_competitors, competitor_product_mappings, data_sources, competitor_prices", "Cross-service ingestion integration"],
  ["live AI discovery uses an approved disposable tenant and authorized sources", "AI_INTEGRATION_BLOCKED", "Observed event, worker run, candidate rows, source decisions, and approved observations are independently verified", "No dedicated test tenant, worker/Redis runtime, or approved source authorization is configured; no live requests were made.", "tenant_competitors, competitor_product_mappings, competitor_prices", "AI/worker test environment"]
];

for (const [scenario, category, expected, actual, tables, owner] of cases) {
  test(`Competitor Management > ${scenario}`, async ({}, testInfo) => {
    blocked(testInfo, category, expected, actual, tables, owner);
  });
}
