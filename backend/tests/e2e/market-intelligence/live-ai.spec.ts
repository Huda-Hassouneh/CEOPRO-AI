import { test, expect } from "@playwright/test";
import { DashboardDatabase } from "../../support/diagnostics/dashboard-db.js";

const enabled = process.env.MARKET_INTELLIGENCE_RUN_LIVE_AI === "1";
const token = process.env.MARKET_INTELLIGENCE_TEST_ACCESS_TOKEN;
const tenantId = process.env.MARKET_INTELLIGENCE_TEST_TENANT_ID;
const userId = process.env.MARKET_INTELLIGENCE_TEST_USER_ID;
const productId = process.env.MARKET_INTELLIGENCE_LIVE_AI_PRODUCT_ID;
const dbUrl = process.env.MARKET_INTELLIGENCE_TEST_DATABASE_URL;
const apiBaseUrl = (process.env.MARKET_INTELLIGENCE_TEST_API_URL || "http://127.0.0.1:5000").replace(/\/$/, "");

test("opt-in live AI pricing integration returns a persisted tenant-owned recommendation", async ({}, testInfo) => {
  test.skip(!enabled, "BLOCKED: this test may call the external AI pricing service and write recommendation evidence; explicitly set MARKET_INTELLIGENCE_RUN_LIVE_AI=1 to enable it.");
  test.skip(!(token && tenantId && userId && productId && dbUrl), "BLOCKED: configure the dedicated test tenant, user, product, access token, and safe test database first.");
  testInfo.annotations.push({ type: "mode", description: "opt-in-live-ai-pricing" });
  testInfo.annotations.push({ type: "tenant", description: tenantId! });
  testInfo.annotations.push({ type: "database-tables", description: "products, competitor_product_mappings, competitor_prices, evidence_records, recommendation_outcomes" });
  testInfo.annotations.push({ type: "ai-dependency", description: "POST /features/pricing/recommend invokes the configured AI pricing client; no scraping or competitor discovery is triggered." });
  const started = Date.now();
  const database = new DashboardDatabase(dbUrl!);
  let stage = "DATABASE_PREFLIGHT";
  try {
    // This read-only preflight refuses non-test DB names, elevated roles, and
    // products that are not visible under the test tenant's RLS context.
    await database.getMarketIntelligenceFacts(tenantId!, userId!, productId!, 30);
    stage = "PRICING_RECOMMENDATION_FAILURE";
    const response = await fetch(`${apiBaseUrl}/features/pricing/recommend?product_id=${encodeURIComponent(productId!)}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json" }
    });
    const body = await response.json().catch(() => null);
    testInfo.annotations.push({ type: "api", description: `POST /features/pricing/recommend?product_id=[configured-test-product] HTTP ${response.status}` });
    expect(response.status, `AI pricing request returned HTTP ${response.status}`).toBe(200);
    const result = body?.data ?? body;
    expect(["OK", "UNKNOWN"]).toContain(result?.status);
    expect(result?.currency).toMatch(/^[A-Z]{3}$/);
    expect(result?.evidence_id).toBeTruthy();
    expect(result?.outcome_id).toBeTruthy();

    stage = "DATABASE_RELATIONSHIP";
    const persistence = await database.getPricingPersistenceFacts(tenantId!, userId!, result.evidence_id, result.outcome_id);
    testInfo.annotations.push({ type: "database-result", description: JSON.stringify(persistence) });
    expect(persistence.evidenceStored).toBe(true);
    expect(persistence.outcomeStored).toBe(true);
    testInfo.annotations.push({ type: "metric-check", description: `pricing recommendation status=${result.status}; evidence persisted=${persistence.evidenceStored}; outcome persisted=${persistence.outcomeStored}; durationMs=${Date.now() - started}` });
  } catch (error) {
    testInfo.annotations.push({ type: "failure-category", description: stage });
    throw error;
  } finally {
    await database.close();
  }
});
