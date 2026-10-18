import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (file) => readFileSync(new URL(`../../${file}`, import.meta.url), "utf8");

test("dashboard route and repository expose the inspected tenant-scoped contract", () => {
  const route = read("src/modules/dashboard/route/dashboard.route.ts");
  const controller = read("src/modules/dashboard/controller/dashboard.controller.ts");
  const repository = read("src/modules/dashboard/repo/dashboard.repo.ts");
  assert.match(route, /authenticateUser[\s\S]*requireTenant/);
  assert.match(controller, /req\.params\.companyId !== tenantId/);
  assert.match(controller, /\[7, 30, 90\]/);
  assert.match(repository, /app\.current_tenant_id/);
  assert.match(repository, /payment_status: "PAID"/);
  assert.match(repository, /currency,/);
  assert.match(repository, /tx\.products\.count/);
  assert.match(repository, /tx\.inventory\.findMany/);
  assert.match(repository, /tx\.sentiment_results\.aggregate/);
  assert.match(repository, /tx\.demand_forecasts\.findMany/);
  assert.match(repository, /tx\.audit_logs\.findMany/);
  assert.doesNotMatch(repository, /tx\.transactions\.(?:count|aggregate)/);
});

test("browser diagnostics keep the real API and DB verifier read-only and tenant scoped", () => {
  const suite = read("tests/e2e/dashboard/dashboard.spec.ts");
  const db = read("tests/support/diagnostics/dashboard-db.ts");
  assert.match(suite, /\/companies\/\$\{tenantId\}\/dashboard/);
  assert.match(suite, /\/dashboard/);
  assert.match(suite, /metrics agree across tenant-scoped PostgreSQL, API, and rendered UI/);
  assert.match(suite, /selectOption/);
  assert.match(suite, /DASHBOARD_TEST_METRIC/);
  assert.match(db, /BEGIN READ ONLY/);
  assert.match(db, /set_config\('app\.current_tenant_id'/);
  assert.match(db, /rolbypassrls/);
  assert.match(db, /database whose name clearly identifies it as test, qa, or e2e/);
  assert.doesNotMatch(db, /\b(?:INSERT|UPDATE|DELETE|TRUNCATE|DROP)\s+\w+/i);
});

test("live ingestion test is explicitly opt-in and uses the actual Data Connections route", () => {
  const suite = read("tests/e2e/dashboard/dashboard-ingestion.spec.ts");
  assert.match(suite, /DASHBOARD_TEST_LIVE_INGESTION === "1"/);
  assert.match(suite, /\/data-connection/);
  assert.match(suite, /getIngestionSnapshot/);
  assert.match(suite, /setTimeout\(resolve, 3_000\)/);
});
