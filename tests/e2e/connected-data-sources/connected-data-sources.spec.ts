import { test, expect, type TestInfo } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { Pool, type PoolClient } from "pg";

type Fixture = {
  plan: "Starter" | "Growth" | "Enterprise" | "Custom";
  tenantId: string;
  userId: string;
  accessToken: string;
  expectedLimit: number | null;
  dataIntegrationEnabled?: boolean;
  foreignTenantId?: string;
};

const apiBaseUrl = (process.env.CONNECTED_DATA_SOURCES_TEST_API_URL || "http://127.0.0.1:5000").replace(/\/$/, "");
const aiBaseUrl = (process.env.CONNECTED_DATA_SOURCES_AI_BASE_URL || "").replace(/\/$/, "");
const aiHostName = (() => { try { return new URL(aiBaseUrl).hostname; } catch { return ""; } })();
const aiOptIn = process.env.CONNECTED_DATA_SOURCES_AI_DB_TARGET === "DISPOSABLE_TEST_DATABASE";
const aiServiceIsLocal = ["localhost", "127.0.0.1", "::1"].includes(aiHostName);
const databaseUrl = process.env.CONNECTED_DATA_SOURCES_TEST_DATABASE_URL;
const fixtures = parseFixtures(process.env.CONNECTED_DATA_SOURCES_TEST_FIXTURES);
const growth = fixtures.find((fixture) => fixture.plan === "Growth");
const dbName = databaseName(databaseUrl);
const safeDatabase = Boolean(databaseUrl && process.env.NODE_ENV !== "production" && /(^|[_-])(test|testing|qa|e2e)([_-]|$)/.test(dbName));
const pool = safeDatabase ? new Pool({ connectionString: databaseUrl, max: 1, connectionTimeoutMillis: 5_000, application_name: "ceopro-connected-data-sources-tests" }) : null;

function parseFixtures(raw?: string): Fixture[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((value): value is Fixture =>
      value && ["Starter", "Growth", "Enterprise", "Custom"].includes(value.plan) &&
      typeof value.tenantId === "string" && typeof value.userId === "string" &&
      typeof value.accessToken === "string" && (value.expectedLimit === null || (Number.isInteger(value.expectedLimit) && value.expectedLimit >= 0))
    );
  } catch {
    return [];
  }
}

function databaseName(url?: string): string {
  try { return url ? new URL(url).pathname.replace(/^\//, "").toLowerCase() : ""; }
  catch { return ""; }
}

function configured(fixture: Fixture): boolean {
  return safeDatabase && Boolean(pool) && Boolean(fixture.accessToken && fixture.tenantId && fixture.userId);
}

function annotate(testInfo: TestInfo, fixture: Fixture, mode: string, category: string, expected: string, tables = "data_sources, plans, plan_features, subscriptions") {
  testInfo.annotations.push({ type: "mode", description: mode });
  testInfo.annotations.push({ type: "failure-category", description: category });
  testInfo.annotations.push({ type: "tenant", description: fixture.tenantId });
  testInfo.annotations.push({ type: "plan", description: fixture.plan });
  testInfo.annotations.push({ type: "effective-source-limit", description: String(fixture.expectedLimit) });
  testInfo.annotations.push({ type: "database-tables", description: tables });
  testInfo.annotations.push({ type: "expected", description: expected });
  if (!safeDatabase) testInfo.annotations.push({ type: "blocked-prerequisite", description: "Set CONNECTED_DATA_SOURCES_TEST_DATABASE_URL to a disposable database whose name contains test, testing, qa, or e2e; production and BYPASSRLS roles are rejected." });
  if (!fixtures.length) testInfo.annotations.push({ type: "blocked-prerequisite", description: "Set CONNECTED_DATA_SOURCES_TEST_FIXTURES to JSON containing isolated plan tenants, user IDs, bearer tokens, and expected limits." });
}

async function withTenantContext(client: PoolClient, fixture: Fixture, readOnly = true) {
  await client.query(readOnly ? "BEGIN READ ONLY" : "BEGIN");
  await client.query("SELECT set_config('app.current_tenant_id', $1, true), set_config('app.current_user_id', $2, true)", [fixture.tenantId, fixture.userId]);
  const role = await client.query<{ rolsuper: boolean; rolbypassrls: boolean }>("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user");
  if (!role.rows[0] || role.rows[0].rolsuper || role.rows[0].rolbypassrls) throw new Error("Connected Data Sources tests require a non-superuser role without BYPASSRLS.");
}

async function activeCount(fixture: Fixture): Promise<number> {
  if (!pool) throw new Error("Safe disposable test database is not configured.");
  const client = await pool.connect();
  try {
    await withTenantContext(client, fixture);
    const result = await client.query<{ count: string }>("SELECT count(*)::text AS count FROM data_sources WHERE tenant_id = $1::uuid AND is_active = TRUE", [fixture.tenantId]);
    await client.query("COMMIT");
    return Number(result.rows[0]?.count ?? 0);
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

async function cleanup(fixture: Fixture, names: string[]) {
  if (!pool || names.length === 0) return;
  const client = await pool.connect();
  try {
    await withTenantContext(client, fixture, false);
    await client.query("UPDATE data_sources SET is_active = FALSE WHERE tenant_id = $1::uuid AND source_name = ANY($2::text[])", [fixture.tenantId, names]);
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK").catch(() => undefined);
    throw error;
  } finally {
    client.release();
  }
}

async function register(fixture: Fixture, name: string, bodyTenantId?: string) {
  const response = await fetch(`${apiBaseUrl}/data-connection/sources`, {
    method: "POST",
    headers: { Authorization: `Bearer ${fixture.accessToken}`, Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      sourceType: "website",
      syncFrequencyMinutes: 1440,
      ...(bodyTenantId ? { tenant_id: bodyTenantId, tenantId: bodyTenantId } : {})
    })
  });
  const body = await response.json().catch(() => null);
  return { status: response.status, body };
}

test.describe("Connected Data Sources: real API + RLS database tests", () => {
  test.afterAll(async () => { await pool?.end(); });

  for (const fixture of fixtures) {
    test(`${fixture.plan} connected-source list matches independently counted active database rows in English and Arabic`, async ({ page }, testInfo) => {
      annotate(testInfo, fixture, "connected-data-sources-browser-e2e", "SOURCE_USAGE_DISPLAY_MISMATCH", "The real API and Data Connections page show the same active-source count; Arabic renders RTL.");
      test.skip(!configured(fixture), "BLOCKED: configure a safe database, real API, frontend, and isolated tenant fixture.");
      const expectedCount = await activeCount(fixture);
      const apiResponse = page.waitForResponse((response) => response.url().includes("/data-connection") && response.request().method() === "GET");
      await page.goto("/");
      await page.evaluate(({ accessToken, tenantId, userId }) => {
        localStorage.setItem("ceopro_auth_session", JSON.stringify({ tenantId, user: { userId }, roleKey: "owner", roles: ["owner"], accessToken }));
        localStorage.setItem("ceopro_locale", "en");
      }, fixture);
      await page.goto("/connect-data");
      const response = await apiResponse;
      expect(response.status()).toBe(200);
      const body = await response.json();
      expect(body?.data?.connectedSources).toHaveLength(expectedCount);
      await expect(page.locator(".connect-data-section__header span").first()).toContainText(String(expectedCount));

      await page.evaluate(() => localStorage.setItem("ceopro_locale", "ar"));
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
      await expect(page.locator(".connect-data-page")).toBeVisible();
      testInfo.annotations.push({ type: "independent-sql-active-count", description: String(expectedCount) });
      testInfo.annotations.push({ type: "api-connected-source-count", description: String(body?.data?.connectedSources?.length ?? "missing") });
      testInfo.annotations.push({ type: "ui-count", description: "English and Arabic rendered from the real API" });
    });

    test(`${fixture.plan} allows exactly its configured active-source capacity`, async ({}, testInfo) => {
      annotate(testInfo, fixture, "connected-data-sources-disposable-db-integration", "SOURCE_LIMIT_BYPASS", `Independent SQL count never exceeds ${fixture.expectedLimit}; one over-limit registration receives HTTP 402.`);
      test.skip(!configured(fixture), "BLOCKED: a safe database, active RLS test role, API, and tenant fixture are required.");
      const initial = await activeCount(fixture);
      testInfo.annotations.push({ type: "active-count-before", description: String(initial) });
      test.skip(initial > fixture.expectedLimit, `Fixture starts over its declared ${fixture.expectedLimit} source limit; no source rows were changed.`);
      const run = randomUUID();
      const names: string[] = [];
      try {
        if (fixture.expectedLimit === null) {
          const name = `cs-unlimited-${run}`;
          names.push(name);
          const result = await register(fixture, name);
          expect(result.status, JSON.stringify(result.body)).toBe(201);
          const after = await activeCount(fixture);
          expect(after).toBe(initial + 1);
          testInfo.annotations.push({ type: "active-count-after", description: String(after) });
          return;
        }
        let actual = initial;
        while (actual < fixture.expectedLimit) {
          const name = `cs-capacity-${run}-${actual}`;
          names.push(name);
          const result = await register(fixture, name);
          testInfo.annotations.push({ type: "registration-response", description: `${result.status}` });
          expect(result.status, JSON.stringify(result.body)).toBe(201);
          actual = await activeCount(fixture);
          expect(actual).toBe(initial + names.length);
        }
        const rejectedName = `cs-capacity-${run}-over`;
        names.push(rejectedName);
        const rejected = await register(fixture, rejectedName);
        testInfo.annotations.push({ type: "over-limit-response", description: String(rejected.status) });
        expect(rejected.status, JSON.stringify(rejected.body)).toBe(402);
        const after = await activeCount(fixture);
        testInfo.annotations.push({ type: "active-count-after", description: String(after) });
        expect(after).toBe(fixture.expectedLimit);
      } finally {
        await cleanup(fixture, names);
      }
    });

    test(`${fixture.plan} request cannot assign its source to another tenant`, async ({}, testInfo) => {
      annotate(testInfo, fixture, "connected-data-sources-tenant-isolation", "TENANT_ISOLATION_FAILURE", "A body-supplied tenant ID cannot override authenticated tenant context.");
      test.skip(!configured(fixture) || !fixture.foreignTenantId, "BLOCKED: configure a second isolated tenant ID in this fixture.");
      const before = await activeCount(fixture);
      test.skip(fixture.expectedLimit !== null && before >= fixture.expectedLimit, "BLOCKED: tenant has no remaining source capacity for a non-destructive tenant-body spoof test.");
      const run = randomUUID();
      const name = `cs-tenant-spoof-${run}`;
      try {
        const result = await register(fixture, name, fixture.foreignTenantId);
        expect(result.status, JSON.stringify(result.body)).toBe(201);
        const client = await pool!.connect();
        try {
          await withTenantContext(client, fixture);
          const own = await client.query<{ count: string }>("SELECT count(*)::text AS count FROM data_sources WHERE tenant_id = $1::uuid AND source_name = $2", [fixture.tenantId, name]);
          const foreign = await client.query<{ count: string }>("SELECT count(*)::text AS count FROM data_sources WHERE tenant_id = $1::uuid AND source_name = $2", [fixture.foreignTenantId, name]);
          await client.query("COMMIT");
          expect(Number(own.rows[0]?.count)).toBe(1);
          expect(Number(foreign.rows[0]?.count)).toBe(0);
        } catch (error) {
          await client.query("ROLLBACK").catch(() => undefined);
          throw error;
        } finally { client.release(); }
      } finally {
        await cleanup(fixture, [name]);
      }
    });
  }

  for (const fixture of fixtures.filter((value) => value.dataIntegrationEnabled === false)) {
    test(`${fixture.plan} with data_integration disabled cannot register a source`, async ({}, testInfo) => {
      annotate(testInfo, fixture, "connected-data-sources-entitlement-integration", "ENTITLEMENT_BYPASS", "The boolean data_integration entitlement denies registration before any source row is added.");
      test.skip(!configured(fixture), "BLOCKED: configure a disabled-entitlement tenant, API, and safe disposable RLS database.");
      const before = await activeCount(fixture);
      const result = await register(fixture, `cs-disabled-${randomUUID()}`);
      const after = await activeCount(fixture);
      testInfo.annotations.push({ type: "api-response", description: String(result.status) });
      testInfo.annotations.push({ type: "active-count-before-after", description: `${before} -> ${after}` });
      expect(result.status).toBe(403);
      expect(after).toBe(before);
    });
  }

  test("Growth concurrent registrations preserve the last available slot", async ({}, testInfo) => {
    const fixture = growth;
    const empty: Fixture = fixture ?? { plan: "Growth", tenantId: "not-configured", userId: "not-configured", accessToken: "", expectedLimit: 5 };
    annotate(testInfo, empty, "connected-data-sources-concurrency", "SOURCE_LIMIT_RACE_CONDITION", "With four active sources and a Growth limit of five, two concurrent requests produce exactly one success and a final SQL count of five.");
    test.skip(!fixture || !configured(fixture), "BLOCKED: configure a Growth test fixture and safe disposable RLS database.");
    const initial = await activeCount(fixture!);
    testInfo.annotations.push({ type: "active-count-before", description: String(initial) });
    testInfo.annotations.push({ type: "concurrent-request-count", description: "2" });
    test.skip(initial !== 4 || fixture!.expectedLimit !== 5, "BLOCKED: Growth race fixture must begin with exactly four active sources and a limit of five.");
    const run = randomUUID();
    const names = [`cs-race-${run}-a`, `cs-race-${run}-b`];
    try {
      const results = await Promise.all(names.map((name) => register(fixture!, name)));
      testInfo.annotations.push({ type: "response-codes", description: results.map((result) => String(result.status)).join(",") });
      const after = await activeCount(fixture!);
      testInfo.annotations.push({ type: "active-count-after", description: String(after) });
      testInfo.annotations.push({ type: "created-source-names", description: names.join(",") });
      expect(results.filter((result) => result.status === 201)).toHaveLength(1);
      expect(results.filter((result) => result.status === 402)).toHaveLength(1);
      expect(after).toBe(5);
    } finally {
      await cleanup(fixture!, names);
    }
  });

  test("AI source registration enforces the same capacity limit", async ({}, testInfo) => {
    const fixture = growth;
    const empty: Fixture = fixture ?? { plan: "Growth", tenantId: "not-configured", userId: "not-configured", accessToken: "", expectedLimit: 5 };
    annotate(testInfo, empty, "connected-data-sources-opt-in-ai-integration", "AI_SOURCE_LIMIT_BYPASS", "An AI-side database-connector registration at capacity creates no active source row.");
    const enabled = Boolean(fixture && configured(fixture) && fixture.expectedLimit === 5 && aiBaseUrl && aiServiceIsLocal && aiOptIn);
    test.skip(!enabled, "BLOCKED: requires an explicitly confirmed disposable AI database, local AI service URL, Growth token, and tenant already at five active sources.");
    const initial = await activeCount(fixture!);
    testInfo.annotations.push({ type: "active-count-before", description: String(initial) });
    test.skip(initial !== 5, "BLOCKED: AI capacity test requires exactly five active Growth sources before the call.");
    const sourceName = `cs-ai-capacity-${randomUUID()}`;
    try {
      const response = await fetch(`${aiBaseUrl}/onboarding/connect/database`, {
        method: "POST",
        headers: { Authorization: `Bearer ${fixture!.accessToken}`, Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({
          source_name: sourceName,
          host: "127.0.0.1",
          port: 5432,
          dbname: "disposable_fixture_only",
          query: "SELECT 1",
          field_mapping: {},
          credentials: { user: "fixture-only", password: "fixture-only" },
          sync_frequency_minutes: 1440
        })
      });
      testInfo.annotations.push({ type: "ai-registration-response", description: String(response.status) });
      const after = await activeCount(fixture!);
      testInfo.annotations.push({ type: "active-count-after", description: String(after) });
      expect([402, 403], "AI registration must reject at capacity").toContain(response.status);
      expect(after).toBe(5);
    } finally {
      await cleanup(fixture!, [sourceName]);
    }
  });

  test("deactivation, reactivation, downgrade, and duplicate lifecycle scenarios are documented blockers", async ({}, testInfo) => {
    testInfo.annotations.push({ type: "mode", description: "connected-data-sources-blocker-diagnostic" });
    testInfo.annotations.push({ type: "failure-category", description: "LIFECYCLE_OR_AI_PREREQUISITE_MISSING" });
    testInfo.annotations.push({ type: "actual", description: "No source activate/deactivate/delete routes exist, no source-identity uniqueness policy is defined, and the response to a plan downgrade below existing active usage is unspecified." });
    test.skip(true, "BLOCKED: requires source lifecycle APIs and an explicit duplicate identity policy. The suite does not fabricate these behaviors.");
  });
});
