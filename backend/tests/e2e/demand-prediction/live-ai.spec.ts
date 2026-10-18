import { test, expect } from "@playwright/test";
import { DashboardDatabase } from "../../support/diagnostics/dashboard-db.js";

const enabled = process.env.DEMAND_PREDICTION_RUN_LIVE_AI === "1";
const token = process.env.DEMAND_PREDICTION_TEST_ACCESS_TOKEN;
const tenantId = process.env.DEMAND_PREDICTION_TEST_TENANT_ID;
const userId = process.env.DEMAND_PREDICTION_TEST_USER_ID;
const productId = process.env.DEMAND_PREDICTION_LIVE_AI_PRODUCT_ID;
const dbUrl = process.env.DEMAND_PREDICTION_TEST_DATABASE_URL;
const horizonDays = Number(process.env.DEMAND_PREDICTION_LIVE_AI_HORIZON_DAYS || 7);
const apiBaseUrl = (process.env.DEMAND_PREDICTION_TEST_API_URL || "http://127.0.0.1:5000").replace(/\/$/, "");

test("opt-in live forecast generation returns a tenant-owned forecast and linked evidence", async ({}, testInfo) => {
  test.skip(!enabled, "BLOCKED: this test calls the configured external AI service and writes forecast/evidence rows. Explicitly set DEMAND_PREDICTION_RUN_LIVE_AI=1 to enable it.");
  test.skip(!(token && tenantId && userId && productId && dbUrl), "BLOCKED: configure the dedicated test tenant, user, product, access token, and safe test database first.");
  test.skip(!Number.isInteger(horizonDays) || horizonDays < 1 || horizonDays > 60, "BLOCKED: DEMAND_PREDICTION_LIVE_AI_HORIZON_DAYS must be an integer from 1 to 60.");
  testInfo.annotations.push({ type: "mode", description: "opt-in-live-ai-demand-forecast" });
  testInfo.annotations.push({ type: "tenant", description: tenantId! });
  testInfo.annotations.push({ type: "database-tables", description: "products, transactions, inventory, demand_forecasts, evidence_records" });
  testInfo.annotations.push({ type: "ai-dependency", description: "POST /forecasting/demand/:productId/generate calls Gradio analytics/forecast; no mocked output is used." });
  const database = new DashboardDatabase(dbUrl!);
  test.setTimeout(660_000);
  const startedAt = Date.now();
  let stage = "READ_ONLY_PREFLIGHT";
  try {
    const today = new Date().toISOString().slice(0, 10);
    const preflight = await database.getDemandPredictionFacts(tenantId!, userId!, today, 7, productId!);
    expect(preflight.products.some(row => row.productId === productId)).toBe(true);
    const historicalSales = preflight.sales.filter(row => row.productId === productId);
    testInfo.annotations.push({ type: "database-result", description: JSON.stringify({ productVisible: true, dailySalesRows: historicalSales.length, inputWindowDays: 365 }) });
    if (historicalSales.length === 0) {
      testInfo.annotations.push({ type: "failure-category", description: "HISTORICAL_DATA_MISSING" });
      throw new Error("Live forecast is blocked because the selected test product has no historical transaction rows in the prior 365 days.");
    }
    stage = "LIVE_AI_GENERATION";
    const response = await fetch(`${apiBaseUrl}/forecasting/demand/${encodeURIComponent(productId!)}/generate`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ horizon_days: horizonDays }),
      signal: AbortSignal.timeout(600_000)
    });
    const body = await response.json().catch(() => null);
    testInfo.annotations.push({ type: "api", description: `POST /forecasting/demand/[configured-product]/generate horizon_days=${horizonDays} HTTP ${response.status}` });
    expect(response.status, `Forecast generation returned HTTP ${response.status}`).toBe(200);
    const result = body?.data;
    expect(result?.product_id).toBe(productId);
    expect(result?.status).toBe("OK");
    expect(result?.prediction_kind).toBe("target_day");
    expect(result?.forecast_start_date).toBe(result?.forecast_target_date);
    expect(result?.forecast_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(result?.evidence_id).toMatch(/^[0-9a-f-]{36}$/i);
    expect(Number.isFinite(result?.expected_demand)).toBe(true);
    expect(result.expected_demand).toBeGreaterThanOrEqual(0);
    expect(result.forecast_start_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(result.forecast_target_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    testInfo.annotations.push({ type: "forecast-horizon", description: `requested=${horizonDays}; persisted range=${result.forecast_start_date}..${result.forecast_target_date}; returned expected_demand=${result.expected_demand}; target-day prediction; requested horizon is not an aggregate demand total` });

    stage = "DATABASE_PERSISTENCE";
    const persisted = await database.getForecastPersistenceFacts(tenantId!, userId!, productId!, result.forecast_id, result.evidence_id);
    expect(persisted.forecastStored).toBe(true);
    expect(persisted.evidenceStored).toBe(true);
    testInfo.annotations.push({ type: "database-result", description: JSON.stringify(persisted) });
    testInfo.annotations.push({ type: "metric-check", description: `forecast row and linked evidence exist under tenant=${tenantId}; durationMs=${Date.now() - startedAt}` });
  } catch (error) {
    if (!testInfo.annotations.some(item => item.type === "failure-category")) testInfo.annotations.push({ type: "failure-category", description: stage === "LIVE_AI_GENERATION" ? "FORECAST_GENERATION_FAILURE" : "TEST_ENVIRONMENT" });
    throw error;
  } finally {
    await database.close();
  }
});
