import { test, expect, type Page, type TestInfo } from "@playwright/test";
import { DashboardDatabase, type DashboardDbFacts } from "../../support/diagnostics/dashboard-db.js";

const token = process.env.DASHBOARD_TEST_ACCESS_TOKEN;
const tenantId = process.env.DASHBOARD_TEST_TENANT_ID;
const userId = process.env.DASHBOARD_TEST_USER_ID;
const apiBaseUrl = (process.env.DASHBOARD_TEST_API_URL || "http://127.0.0.1:5000").replace(/\/$/, "");
const dbUrl = process.env.DASHBOARD_TEST_DATABASE_URL;
const requestedMetric = process.env.DASHBOARD_TEST_METRIC;
const dashboardMetricIds = new Set(["totalSales", "totalProducts", "trackedCompetitors", "revenues", "growth", "inventoryStatus", "marketSentiment"]);
const enabled = Boolean(token && tenantId && userId && dbUrl);
if (!enabled) test.skip(true, "BLOCKED: configure authenticated test tenant credentials and read-only test database.");
if (requestedMetric && !dashboardMetricIds.has(requestedMetric)) throw new Error("DASHBOARD_TEST_METRIC must be one of: totalSales, totalProducts, trackedCompetitors, revenues, growth, inventoryStatus, marketSentiment.");
let database: DashboardDatabase | undefined;

test.beforeAll(async () => {
  if (enabled) database = new DashboardDatabase(dbUrl!);
});
test.afterAll(async () => { await database?.close(); });

function gate(testInfo: { skip: (condition: boolean, description?: string) => void }) {
  testInfo.skip(!enabled, "BLOCKED: set DASHBOARD_TEST_ACCESS_TOKEN, DASHBOARD_TEST_TENANT_ID, DASHBOARD_TEST_USER_ID and a safe DASHBOARD_TEST_DATABASE_URL to run authenticated DB-backed diagnostics.");
}

async function getDashboard(periodDays: number) {
  const response = await fetch(`${apiBaseUrl}/companies/${tenantId}/dashboard?periodDays=${periodDays}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" }
  });
  const body = await response.json().catch(() => null);
  return { response, body };
}

function metric(data: any, id: string) {
  const found = data.metrics?.find((item: any) => item.id === id);
  expect(found, `Dashboard API metric ${id} is missing`).toBeTruthy();
  return found;
}

function expectedSentiment(score: number | null) {
  if (score == null) return null;
  return score > 0.1 ? "positive" : score < -0.1 ? "negative" : "neutral";
}

async function expectUiMetric(page: Page, label: string, expected: string, testInfo: TestInfo) {
  const card = page.locator(".dashboard-kpi-card").filter({ hasText: label });
  await expect(card).toHaveCount(1);
  const displayed = (await card.locator("strong").innerText()).trim();
  testInfo.annotations.push({ type: "ui-metric", description: `${label}: expected=${expected} displayed=${displayed}` });
  await expect(card.locator("strong")).toHaveText(expected);
}

test("dashboard metrics agree across tenant-scoped PostgreSQL, API, and rendered UI", async ({ page, baseURL }, testInfo) => {
  gate(testInfo);
  testInfo.annotations.push({ type: "mode", description: "authenticated-live-dashboard" });
  const startedAt = new Date().toISOString();
  const browserIssues: string[] = [];
  page.on("pageerror", error => browserIssues.push(`pageerror: ${error.message}`));
  page.on("console", message => { if (message.type() === "error") browserIssues.push(`console: ${message.text()}`); });
  page.on("requestfailed", request => browserIssues.push(`requestfailed: ${request.method()} ${new URL(request.url()).pathname} (${request.failure()?.errorText})`));

  const periodDays = Number(process.env.DASHBOARD_TEST_PERIOD_DAYS || 30);
  const [api, facts] = await Promise.all([
    getDashboard(periodDays),
    database!.getFacts(tenantId!, userId!, periodDays)
  ]);
  testInfo.annotations.push({ type: "database-tables", description: "companies, invoices, products, inventory, tenant_competitors, reviews, sentiment_results" });
  testInfo.annotations.push({ type: "tenant", description: tenantId! });
  testInfo.annotations.push({ type: "api", description: `GET /companies/:companyId/dashboard?periodDays=${periodDays} HTTP ${api.response.status}` });
  expect(api.response.status, `GET /companies/:companyId/dashboard returned ${api.response.status}; response body is redacted from default artifacts`).toBe(200);
  expect(api.body?.status).toBe("success");
  const data = api.body.data;

  const expectedGrowth = facts.previousRevenue <= 0 ? null : Number((((facts.revenue - facts.previousRevenue) / facts.previousRevenue) * 100).toFixed(1));
  const expectedInventory = facts.inventory.total ? Math.round(facts.inventory.inStock / facts.inventory.total * 100) : null;
  const checks: Array<[string, unknown, unknown]> = [
    ["totalSales", metric(data, "totalSales").value, facts.paidInvoiceCount],
    ["totalProducts", metric(data, "totalProducts").value, facts.productCount],
    ["trackedCompetitors", metric(data, "trackedCompetitors").value, facts.trackedCompetitors],
    ["revenues", Number(metric(data, "revenues").value), facts.revenue],
    ["growth", metric(data, "growth").value, expectedGrowth],
    ["inventoryStatus", metric(data, "inventoryStatus").value, expectedInventory],
    ["marketSentiment", metric(data, "marketSentiment").value, expectedSentiment(facts.sentimentAverage)]
  ];
  const selectedChecks = checks.filter(([id]) => !requestedMetric || id === requestedMetric);
  for (const [id, actual, expected] of selectedChecks) {
    testInfo.annotations.push({ type: "metric-check", description: `${id}: expected=${String(expected)} actual=${String(actual)} source=PostgreSQL/API` });
    if (id === "revenues" && typeof actual === "number" && typeof expected === "number") {
      expect(Math.abs(actual - expected), `${id} API value differs from tenant-scoped PostgreSQL computation`).toBeLessThan(0.005);
    } else {
      expect(actual, `${id} API value differs from tenant-scoped PostgreSQL computation`).toEqual(expected);
    }
  }

  expect(data.period.days).toBe(periodDays);
  expect(data.salesOverview.points).toHaveLength(periodDays);
  expect(data.salesOverview.points.reduce((sum: number, point: any) => sum + Number(point.value), 0)).toBeCloseTo(facts.revenue, 2);
  expect(data.salesOverview.currency).toBe(facts.currency);
  if (facts.inventory.total === 0) expect(data.inventoryStatus).toBeNull();
  else {
    expect(data.inventoryStatus.totals).toEqual({ inStock: facts.inventory.inStock, lowStock: facts.inventory.lowStock, outOfStock: facts.inventory.outOfStock, totalItems: facts.inventory.total });
  }
  expect(data.company.id).toBe(tenantId);

  await page.addInitScript(({ accessToken, id, actor }) => {
    localStorage.setItem("ceopro_auth_session", JSON.stringify({ tenantId: id, user: { userId: actor }, roleKey: "owner", roles: ["owner"], accessToken }));
    localStorage.setItem("ceopro_locale", "en");
  }, { accessToken: token!, id: tenantId!, actor: userId! });
  await page.goto(new URL("/dashboard", baseURL).toString());
  await expect(page.getByRole("heading", { name: "Executive Dashboard", exact: true })).toBeVisible();
  if (facts.paidInvoiceCount === 0 && (!requestedMetric || requestedMetric === "totalSales")) {
    testInfo.annotations.push({ type: "failure-category", description: "INCORRECT_EMPTY_STATE" });
    await expect(page.getByText("No sales data", { exact: true })).toBeVisible();
    await expect(page.locator(".dashboard-sales-chart")).toHaveCount(0);
  }
  const uiChecks: Array<[string, string, string]> = [
    ["totalSales", "Paid Invoices", new Intl.NumberFormat("en").format(facts.paidInvoiceCount)],
    ["totalProducts", "Total Products", new Intl.NumberFormat("en").format(facts.productCount)],
    ["trackedCompetitors", "Tracked Competitors", new Intl.NumberFormat("en").format(facts.trackedCompetitors)],
    ["revenues", "Revenues", new Intl.NumberFormat("en", { style: "currency", currency: facts.currency }).format(facts.revenue)],
    ["inventoryStatus", "Inventory Status", expectedInventory == null ? "—" : `${new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(expectedInventory)}%`],
    ["marketSentiment", "Review Sentiment", facts.sentimentAverage == null ? "—" : expectedSentiment(facts.sentimentAverage)!],
    ["growth", "Growth", expectedGrowth == null ? "—" : `${expectedGrowth > 0 ? "+" : ""}${new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(expectedGrowth)}%`]
  ];
  for (const [id, label, expected] of uiChecks.filter(([id]) => !requestedMetric || id === requestedMetric)) await expectUiMetric(page, label, expected, testInfo);
  if (!requestedMetric) {
    await expect(page.locator(".dashboard-sales-chart")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Upcoming Demand Forecasts" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Competitor Price Comparison" })).toBeVisible();

    if (facts.inventory.total > 0) {
      await page.getByRole("button", { name: /view inventory/i }).click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await expect(page.getByRole("dialog").getByRole("table")).toBeVisible();
      await page.getByRole("dialog").getByRole("button", { name: /close/i }).click();
    }
    await page.getByRole("button", { name: /view all/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("dialog").getByRole("button", { name: /close/i }).click();

    const periodSelect = page.locator(".dashboard-date-select");
    for (const nextPeriod of [7, 90]) {
      const apiPromise = page.waitForResponse(response => response.url().includes(`/companies/${tenantId}/dashboard`) && response.url().includes(`periodDays=${nextPeriod}`));
      await periodSelect.selectOption(String(nextPeriod));
      expect((await apiPromise).status()).toBe(200);
      await expect(periodSelect).toHaveValue(String(nextPeriod));
    }

    await page.evaluate(() => localStorage.setItem("ceopro_locale", "ar"));
    await page.reload();
    await expect(page.getByRole("heading", { name: "لوحة التحكم التنفيذية", exact: true })).toBeVisible();
    await expect(page.locator(".dashboard-page")).toHaveAttribute("dir", "rtl");
    const arNumber = (value: number) => new Intl.NumberFormat("ar", { maximumFractionDigits: 1 }).format(value);
    const arCurrency = (value: number) => new Intl.NumberFormat("ar", { style: "currency", currency: facts.currency }).format(value);
    const arSentiment = facts.sentimentAverage == null ? "—" : ({ positive: "إيجابي", neutral: "محايد", negative: "سلبي" } as const)[expectedSentiment(facts.sentimentAverage)!];
    const arabicUiChecks: Array<[string, string, string]> = [
      ["totalSales", "الفواتير المدفوعة", arNumber(facts.paidInvoiceCount)],
      ["totalProducts", "إجمالي المنتجات", arNumber(facts.productCount)],
      ["trackedCompetitors", "المنافسون المتابَعون", arNumber(facts.trackedCompetitors)],
      ["revenues", "الإيرادات", arCurrency(facts.revenue)],
      ["inventoryStatus", "حالة المخزون", expectedInventory == null ? "—" : `${arNumber(expectedInventory)}%`],
      ["marketSentiment", "مشاعر المراجعات", arSentiment],
      ["growth", "النمو", expectedGrowth == null ? "—" : `${expectedGrowth > 0 ? "+" : ""}${arNumber(expectedGrowth)}%`]
    ];
    for (const [id, label, expected] of arabicUiChecks) await expectUiMetric(page, label, expected, testInfo);
  }
  expect(browserIssues, `Browser issues: ${browserIssues.join(" | ")}`).toEqual([]);
  testInfo.annotations.push({ type: "run-started-at", description: startedAt });
  testInfo.annotations.push({ type: "result-scope", description: `Read-only DB verification; no records created or deleted. tenant=${facts.tenantId}; currency=${facts.currency}; excludedOtherCurrencyInvoices=${facts.invoiceCurrencyExcluded}` });
});

test("dashboard rejects invalid period and cross-tenant path access", async ({}, testInfo) => {
  gate(testInfo);
  testInfo.annotations.push({ type: "mode", description: "authenticated-live-api-security" });
  const invalid = await fetch(`${apiBaseUrl}/companies/${tenantId}/dashboard?periodDays=14`, { headers: { Authorization: `Bearer ${token}` } });
  expect(invalid.status, "Unsupported period should be rejected by the dashboard controller").toBe(400);
  const otherTenant = process.env.DASHBOARD_TEST_OTHER_TENANT_ID;
  if (!otherTenant) {
    testInfo.annotations.push({ type: "coverage", description: "Cross-tenant ownership probe SKIPPED: provide DASHBOARD_TEST_OTHER_TENANT_ID for a known unrelated tenant." });
    return;
  }
  const crossTenant = await fetch(`${apiBaseUrl}/companies/${otherTenant}/dashboard?periodDays=30`, { headers: { Authorization: `Bearer ${token}` } });
  expect([401, 403, 404]).toContain(crossTenant.status);
});
