import { test, expect, type Page, type TestInfo } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { DashboardDatabase } from "../../support/diagnostics/dashboard-db.js";

const token = process.env.DEMAND_PREDICTION_TEST_ACCESS_TOKEN;
const tenantId = process.env.DEMAND_PREDICTION_TEST_TENANT_ID;
const userId = process.env.DEMAND_PREDICTION_TEST_USER_ID;
const dbUrl = process.env.DEMAND_PREDICTION_TEST_DATABASE_URL;
const apiBaseUrl = (process.env.DEMAND_PREDICTION_TEST_API_URL || "http://127.0.0.1:5000").replace(/\/$/, "");
const frontendUrl = (process.env.DEMAND_PREDICTION_TEST_FRONTEND_URL || "http://127.0.0.1:5173").replace(/\/$/, "");
const enabled = Boolean(token && tenantId && userId);
if (!enabled) test.skip(true, "BLOCKED: configure the dedicated Demand Prediction tenant, user, and access token.");

async function getOverview(periodDays = 30, productId = "all") {
  const response = await fetch(`${apiBaseUrl}/forecasting/demand?periodDays=${periodDays}&productId=${encodeURIComponent(productId)}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" }
  });
  const body = await response.json().catch(() => null);
  return { response, body };
}

function annotateEnabled(testInfo: TestInfo) {
  testInfo.skip(!enabled, "BLOCKED: set DEMAND_PREDICTION_TEST_ACCESS_TOKEN, DEMAND_PREDICTION_TEST_TENANT_ID, and DEMAND_PREDICTION_TEST_USER_ID.");
  testInfo.annotations.push({ type: "mode", description: "authenticated-demand-prediction-e2e" });
  testInfo.annotations.push({ type: "tenant", description: tenantId! });
  testInfo.annotations.push({ type: "api", description: "GET /forecasting/demand?periodDays={7|30}&productId=all" });
  testInfo.annotations.push({ type: "database-tables", description: "products, transactions, inventory, demand_forecasts, model_versions, recommendation_outcomes" });
}

function metric(data: any, id: string) {
  const result = data.metrics?.find((item: any) => item.id === id);
  expect(result, `Demand Prediction API metric ${id} is missing`).toBeTruthy();
  return result;
}

const addDays = (date: string, count: number) => new Date(new Date(`${date}T00:00:00.000Z`).getTime() + count * 86_400_000).toISOString().slice(0, 10);

/** Independent test-side calculation from persisted rows; does not call backend calculation helpers. */
function expectedPeriodTotal(rows: any[], start: string, days: number, asOf: string) {
  const windows = new Map<string, any>();
  for (const row of rows) {
    if (row.createdAt && row.createdAt > asOf) continue;
    const first = row.startDate && row.endDate ? row.startDate : row.targetDate;
    const last = row.startDate && row.endDate ? row.endDate : row.targetDate;
    if (!first || !last || last < first || row.expectedDemand < 0) continue;
    const key = `${first}:${last}`;
    if (!windows.has(key)) windows.set(key, { ...row, first, last });
  }
  const end = addDays(start, days - 1);
  const selected = [...windows.values()].filter(row => row.first <= end && row.last >= start && row.first >= start && row.last <= end);
  const exact = selected.find(row => row.first === start && row.last === end);
  if (exact) return exact.expectedDemand;
  const daily = selected.filter(row => row.first === row.last);
  const covers = (candidates: any[]) => {
    const dates = new Set<string>();
    let overlap = false;
    for (const row of candidates) for (let date = row.first; date <= row.last; date = addDays(date, 1)) {
      if (dates.has(date)) overlap = true;
      dates.add(date);
    }
    return !overlap && dates.size === days && dates.has(start) && dates.has(end);
  };
  if (daily.length === days && covers(daily)) return daily.reduce((sum, row) => sum + row.expectedDemand, 0);
  const intervals = selected.filter(row => row.first !== row.last);
  return intervals.length && covers(intervals) ? intervals.reduce((sum, row) => sum + row.expectedDemand, 0) : null;
}

async function expectMetric(page: Page, label: string, value: string) {
  const card = page.locator(".demand-approved-metric").filter({ hasText: label });
  await expect(card).toHaveCount(1);
  await expect(card.locator("strong")).toHaveText(value);
}

test("overview API and UI show the same tenant forecast values, periods, and empty-data semantics", async ({ page }, testInfo) => {
  annotateEnabled(testInfo);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("requestfailed", request => errors.push(`${request.method()} ${new URL(request.url()).pathname}: ${request.failure()?.errorText}`));

  const api = await getOverview(30);
  testInfo.annotations.push({ type: "api", description: `GET /forecasting/demand?periodDays=30 HTTP ${api.response.status}` });
  expect(api.response.status).toBe(200);
  expect(api.body?.status).toBe("success");
  const data = api.body.data;
  expect(data.filters.periodDays).toBe(30);
  expect(data.filters.timeZone).toBe("UTC");
  expect([7, 30]).toEqual(expect.arrayContaining(data.availablePeriods));
  for (const id of ["next30Forecast", "productsForecasted", "predictedIncrease", "predictedDecrease", "stableDemand"]) {
    metric(data, id);
  }
  for (const product of data.forecasts) {
    expect(product.coverage.periodDays).toBe(30);
    expect(product.expectedDemand === null || Number.isFinite(product.expectedDemand)).toBe(true);
    if (product.coverage.status !== "complete") expect(product.expectedDemand).toBeNull();
    if (product.coverage.status === "complete") expect(product.coverage.coveredDays).toBe(30);
  }
  const complete = data.forecasts.filter((row: any) => row.coverage.status === "complete");
  const expectedTotal = complete.length ? complete.reduce((sum: number, row: any) => sum + row.expectedDemand, 0) : null;
  expect(metric(data, "next30Forecast").value).toBe(expectedTotal);
  testInfo.annotations.push({ type: "metric-check", description: `30-day overview total expected=${expectedTotal} actual=${metric(data, "next30Forecast").value}; products contributing=${complete.length}/${data.forecasts.length}; independent of chart data` });
  testInfo.annotations.push({ type: "result-scope", description: "Uses current tenant data read-only. API/UI consistency and coverage semantics are checked; a configured test database enables an independent PostgreSQL calculation." });
  if (dbUrl) {
    const database = new DashboardDatabase(dbUrl);
    try {
      const facts = await database.getDemandPredictionFacts(tenantId!, userId!, data.filters.startDate, 30);
      const sourceRows = facts.forecasts;
      const dbExpected = facts.products.map(product => ({
        productId: product.productId,
        total: expectedPeriodTotal(sourceRows.filter(row => row.productId === product.productId), data.filters.startDate, 30, data.generatedAt)
      }));
      const expectedDbTotal = dbExpected.some(row => row.total != null) ? dbExpected.reduce((sum, row) => sum + (row.total ?? 0), 0) : null;
      expect(metric(data, "next30Forecast").value).toBe(expectedDbTotal);
      for (const expected of dbExpected) {
        const apiProduct = data.forecasts.find((row: any) => row.id === expected.productId);
        if (apiProduct) expect(apiProduct.expectedDemand).toBe(expected.total);
      }
      testInfo.annotations.push({ type: "database-result", description: JSON.stringify({ sourceRows: sourceRows.length, products: facts.products.length, inventoryRows: facts.inventory.length, salesRows: facts.sales.length, expectedTotal: expectedDbTotal }) });
      testInfo.annotations.push({ type: "metric-check", description: `PostgreSQL independent total expected=${expectedDbTotal} actual=${metric(data, "next30Forecast").value}; latest row per exact window; no summing overlapping/partial coverage` });
    } finally { await database.close(); }
  } else {
    testInfo.annotations.push({ type: "database-result", description: "BLOCKED: set DEMAND_PREDICTION_TEST_DATABASE_URL to compare forecast API calculations with RLS-scoped PostgreSQL source rows." });
  }

  await page.addInitScript(({ accessToken, id, actor }) => {
    localStorage.setItem("ceopro_auth_session", JSON.stringify({ tenantId: id, user: { userId: actor }, roleKey: "owner", roles: ["owner"], accessToken }));
    localStorage.setItem("ceopro_locale", "en");
  }, { accessToken: token!, id: tenantId!, actor: userId! });
  await page.goto(`${frontendUrl}/demand`);
  if (!data.products?.length) {
    await expect(page.getByText("No products available", { exact: true })).toBeVisible();
    testInfo.annotations.push({ type: "empty-state", description: "API returned no active products and the frontend presented its configured empty-products message." });
    return;
  }
  await expect(page.getByRole("heading", { name: "Demand Prediction", exact: true })).toBeVisible();
  await expectMetric(page, "Next 30 Days Forecast", expectedTotal == null ? "—" : `${new Intl.NumberFormat("en").format(expectedTotal)} units`);
  await expectMetric(page, "Products with Full Forecasts", new Intl.NumberFormat("en").format(complete.length));
  await expect(page.getByRole("region", { name: "Demand prediction summary" })).toBeVisible();

  const period = page.getByLabel("Date range");
  const nextSeven = page.waitForResponse(response => response.url().includes("/forecasting/demand") && response.url().includes("periodDays=7"));
  await period.selectOption("7");
  expect((await nextSeven).status()).toBe(200);
  await expect(period).toHaveValue("7");
  testInfo.annotations.push({ type: "filter-check", description: "period selector sent periodDays=7 and received HTTP 200" });

  const productSelector = page.getByLabel("Product");
  const nextProduct = data.products.find((row: any) => row.id !== "all");
  if (nextProduct) {
    const filtered = page.waitForResponse(response => response.url().includes("/forecasting/demand") && response.url().includes(`productId=${nextProduct.id}`));
    await productSelector.selectOption(nextProduct.id);
    expect((await filtered).status()).toBe(200);
  }

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export to PDF" }).first().click()
  ]);
  const pdfPath = testInfo.outputPath("demand-prediction-report.pdf");
  await download.saveAs(pdfPath);
  const pdfBytes = await readFile(pdfPath);
  expect(pdfBytes.subarray(0, 5).toString("ascii")).toBe("%PDF-");
  expect(pdfBytes.byteLength).toBeGreaterThan(1_000);
  testInfo.annotations.push({ type: "pdf-check", description: `download=${download.suggestedFilename()} bytes=${pdfBytes.byteLength}; valid PDF signature` });

  await page.evaluate(() => localStorage.setItem("ceopro_locale", "ar"));
  await page.reload();
  await expect(page.locator(".demand-approved-page")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "التنبؤ بالطلب", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("foreign tenant product IDs do not leak Demand Prediction products", async ({}, testInfo) => {
  annotateEnabled(testInfo);
  const foreignProductId = process.env.DEMAND_PREDICTION_TEST_OTHER_TENANT_PRODUCT_ID;
  testInfo.skip(!foreignProductId, "BLOCKED: set DEMAND_PREDICTION_TEST_OTHER_TENANT_PRODUCT_ID from a second disposable tenant.");
  const result = await getOverview(30, foreignProductId!);
  expect(result.response.status).toBe(200);
  expect(result.body?.data?.filters?.productId).not.toBe(foreignProductId);
  expect(result.body?.data?.products?.some((row: any) => row.id === foreignProductId)).toBe(false);
  testInfo.annotations.push({ type: "failure-category", description: "TENANT_ISOLATION" });
});

test("Starter entitlement blocks Demand Prediction", async ({}, testInfo) => {
  const starterToken = process.env.DEMAND_PREDICTION_STARTER_ACCESS_TOKEN;
  testInfo.skip(!starterToken, "BLOCKED: set DEMAND_PREDICTION_STARTER_ACCESS_TOKEN for a disposable Starter tenant.");
  const response = await fetch(`${apiBaseUrl}/forecasting/demand?periodDays=30&productId=all`, { headers: { Authorization: `Bearer ${starterToken}`, Accept: "application/json" } });
  testInfo.annotations.push({ type: "mode", description: "starter-entitlement-regression" });
  testInfo.annotations.push({ type: "api", description: `GET /forecasting/demand as Starter HTTP ${response.status}` });
  expect([401, 403]).toContain(response.status);
});
