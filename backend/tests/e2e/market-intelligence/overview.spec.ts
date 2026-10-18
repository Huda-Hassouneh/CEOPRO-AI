import { test, expect, type Page, type TestInfo } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { DashboardDatabase } from "../../support/diagnostics/dashboard-db.js";

const token = process.env.MARKET_INTELLIGENCE_TEST_ACCESS_TOKEN;
const tenantId = process.env.MARKET_INTELLIGENCE_TEST_TENANT_ID;
const userId = process.env.MARKET_INTELLIGENCE_TEST_USER_ID;
const apiBaseUrl = (process.env.MARKET_INTELLIGENCE_TEST_API_URL || "http://127.0.0.1:5000").replace(/\/$/, "");
const frontendUrl = (process.env.MARKET_INTELLIGENCE_TEST_FRONTEND_URL || "http://127.0.0.1:5173").replace(/\/$/, "");
const dbUrl = process.env.MARKET_INTELLIGENCE_TEST_DATABASE_URL;
const enabled = Boolean(token && tenantId && userId && dbUrl);
if (!enabled) test.skip(true, "BLOCKED: configure the dedicated Market Intelligence test tenant, access token, and safe test database.");
let database: DashboardDatabase | undefined;

test.beforeAll(async () => { if (enabled) database = new DashboardDatabase(dbUrl!); });
test.afterAll(async () => { await database?.close(); });

async function getOverview(productId?: string, periodDays = 30) {
  const params = new URLSearchParams({ periodDays: String(periodDays) });
  if (productId) params.set("productId", productId);
  const response = await fetch(`${apiBaseUrl}/market-intelligence?${params}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" }
  });
  const body = await response.json().catch(() => null);
  return { response, body };
}

function annotateEnabled(testInfo: TestInfo) {
  testInfo.skip(!enabled, "BLOCKED: set MARKET_INTELLIGENCE_TEST_ACCESS_TOKEN, MARKET_INTELLIGENCE_TEST_TENANT_ID, MARKET_INTELLIGENCE_TEST_USER_ID, and a dedicated safe MARKET_INTELLIGENCE_TEST_DATABASE_URL.");
  testInfo.annotations.push({ type: "mode", description: "authenticated-market-intelligence-e2e" });
  testInfo.annotations.push({ type: "tenant", description: tenantId! });
  testInfo.annotations.push({ type: "frontend-component", description: "MarketIntelligenceOverviewPage" });
}

function metric(data: any, id: string) {
  const value = data.metrics?.find((item: any) => item.id === id);
  expect(value, `Market Intelligence API metric ${id} is missing`).toBeTruthy();
  return value;
}

async function expectMetricCard(page: Page, label: string, expected: string) {
  const card = page.locator(".market-main-metric").filter({ hasText: label });
  await expect(card).toHaveCount(1);
  await expect(card.locator("strong")).toHaveText(expected);
}

test("overview totals and scores agree with independent tenant-scoped database calculations", async ({ page }, testInfo) => {
  annotateEnabled(testInfo);
  testInfo.annotations.push({ type: "database-tables", description: "products, competitor_product_mappings, tenant_competitors, competitor_prices, competitor_score_snapshots" });
  const startedAt = new Date().toISOString();
  const issues: string[] = [];
  page.on("pageerror", error => issues.push(error.message));
  page.on("console", message => { if (message.type() === "error") issues.push(message.text()); });
  page.on("requestfailed", request => issues.push(`${request.method()} ${new URL(request.url()).pathname}: ${request.failure()?.errorText}`));

  const api = await getOverview();
  testInfo.annotations.push({ type: "api", description: `GET /market-intelligence?periodDays=30 HTTP ${api.response.status}` });
  expect(api.response.status).toBe(200);
  expect(api.body?.status).toBe("success");
  const data = api.body.data;
  if (!data.products?.length || !data.selectedProduct?.id) {
    testInfo.annotations.push({ type: "coverage", description: "No active products: API returned the real empty products state; score calculations are unavailable for this tenant." });
    await page.addInitScript(({ accessToken, id, actor }) => {
      localStorage.setItem("ceopro_auth_session", JSON.stringify({ tenantId: id, user: { userId: actor }, roleKey: "owner", roles: ["owner"], accessToken }));
      localStorage.setItem("ceopro_locale", "en");
    }, { accessToken: token!, id: tenantId!, actor: userId! });
    await page.goto(`${frontendUrl}/market`);
    await expect(page.getByText("No products available", { exact: false })).toBeVisible();
    return;
  }

  const facts = await database!.getMarketIntelligenceFacts(tenantId!, userId!, data.selectedProduct.id, 30);
  testInfo.annotations.push({ type: "expected-calculation", description: `competitors=${facts.totalCompetitors}; pricing-score=mean of rounded per-mapping 0–10 scores from latest eligible same-currency exact prices; composite-score=mean of latest 0–100 snapshots` });
  testInfo.annotations.push({ type: "database-result", description: JSON.stringify({ competitorRows: facts.competitorRows.length, priceRows: facts.competitorRows.filter(row => row.latestPrice !== null).length, snapshots: facts.competitorRows.filter(row => row.compositeScore !== null).length, currency: facts.currency }) });

  const total = metric(data, "totalCompetitors").value;
  const pricing = metric(data, "averagePriceScore").value;
  const composite = metric(data, "averageCompositeScore").value;
  const round1 = (value: number | null) => value == null ? null : Number(value.toFixed(1));
  const expectedPricing = round1(facts.averagePriceScore);
  const expectedComposite = round1(facts.averageCompositeScore);
  testInfo.annotations.push({ type: "metric-check", description: `totalCompetitors expected=${facts.totalCompetitors} actual=${total}; tables=competitor_product_mappings,tenant_competitors` });
  testInfo.annotations.push({ type: "metric-check", description: `averagePriceScore expected=${expectedPricing} actual=${pricing}; tables=products,competitor_product_mappings,tenant_competitors,competitor_prices` });
  testInfo.annotations.push({ type: "metric-check", description: `averageCompositeScore expected=${expectedComposite} actual=${composite}; tables=competitor_product_mappings,competitor_score_snapshots; scale=0..100` });
  expect(total).toBe(facts.totalCompetitors);
  expect(pricing).toBe(expectedPricing);
  expect(composite).toBe(expectedComposite);
  expect(metric(data, "averageCompositeScore").format).toBe("score100");
  expect(metric(data, "averagePriceScore").format).toBe("score10");
  const topSegment = metric(data, "topSegmentScore");
  expect(topSegment.format).toBe("score10");
  if (topSegment.value !== null) expect(topSegment.value).toBeGreaterThanOrEqual(0);
  if (topSegment.value !== null) expect(topSegment.value).toBeLessThanOrEqual(10);

  const dbCompetitorIds = facts.competitorRows.map(row => row.competitorId).sort();
  const apiCompetitorIds = data.competitors.map((row: any) => row.competitorId).sort();
  testInfo.annotations.push({ type: "metric-check", description: `competitor rows expected=${dbCompetitorIds.length} actual=${apiCompetitorIds.length}; includes tracked active mappings with or without price records` });
  expect(apiCompetitorIds).toEqual(dbCompetitorIds);
  for (const row of facts.competitorRows) {
    const actual = data.competitors.find((item: any) => item.competitorId === row.competitorId);
    expect(actual, `Competitor ${row.competitorId} is missing from API`).toBeTruthy();
    expect(actual.pricingScore).toBe(row.pricingScore);
    if (row.latestPrice === null) {
      expect(actual.pricingScore).toBeNull();
      // A missing price does not erase a valid composite snapshot.
      expect(["partial", "unavailable", "stale"]).toContain(actual.dataStatus);
    }
  }
  expect(data.selectedProduct.currency).toBe(facts.currency);

  await page.addInitScript(({ accessToken, id, actor }) => {
    localStorage.setItem("ceopro_auth_session", JSON.stringify({ tenantId: id, user: { userId: actor }, roleKey: "owner", roles: ["owner"], accessToken }));
    localStorage.setItem("ceopro_locale", "en");
  }, { accessToken: token!, id: tenantId!, actor: userId! });
  await page.goto(`${frontendUrl}/market`);
  await expect(page.getByRole("heading", { name: "Market Intelligence", exact: true })).toBeVisible();
  await expectMetricCard(page, "Total Competitors", new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(facts.totalCompetitors));
  await expectMetricCard(page, "Avg Price Score", expectedPricing === null ? "—" : `${new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(expectedPricing)} / 10`);
  await expectMetricCard(page, "Average Composite Score", expectedComposite === null ? "—" : `${new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(expectedComposite)} / 100`);

  const productSelect = page.locator(".market-main-product select");
  if (data.products.length > 1) {
    const nextProduct = data.products.find((product: any) => product.id !== data.selectedProduct.id);
    const nextApi = page.waitForResponse(response => response.url().includes("/market-intelligence") && response.url().includes(`productId=${nextProduct.id}`));
    await productSelect.selectOption(nextProduct.id);
    const filteredResponse = await nextApi;
    expect(filteredResponse.status()).toBe(200);
    const filteredPayload = await filteredResponse.json();
    expect(filteredPayload.data.selectedProduct.id).toBe(nextProduct.id);
    testInfo.annotations.push({ type: "filter-check", description: `product filter selected=${nextProduct.id} API=${filteredResponse.status()}` });
  }
  const periodSelect = page.locator(".market-main-period");
  const periodResponse = page.waitForResponse(response => response.url().includes("/market-intelligence") && response.url().includes("periodDays=90"));
  await periodSelect.selectOption("90");
  expect((await periodResponse).status()).toBe(200);
  await expect(periodSelect).toHaveValue("90");
  testInfo.annotations.push({ type: "filter-check", description: "reporting period changed 30→90; API request observed" });

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export to PDF" }).first().click()
  ]);
  const pdfPath = testInfo.outputPath("market-intelligence-report.pdf");
  await download.saveAs(pdfPath);
  const pdfBytes = await readFile(pdfPath);
  expect(pdfBytes.subarray(0, 5).toString("ascii")).toBe("%PDF-");
  expect(pdfBytes.byteLength).toBeGreaterThan(1_000);
  testInfo.annotations.push({ type: "pdf-check", description: `download=${download.suggestedFilename()} bytes=${pdfBytes.byteLength}; valid PDF signature` });

  await page.evaluate(() => localStorage.setItem("ceopro_locale", "ar"));
  await page.reload();
  await expect(page.locator(".market-intelligence-main")).toHaveAttribute("dir", "rtl");
  await expect(page.getByText("إجمالي المنافسين", { exact: true })).toBeVisible();
  expect(issues).toEqual([]);
  testInfo.annotations.push({ type: "run-started-at", description: startedAt });
  testInfo.annotations.push({ type: "result-scope", description: "Read-only DB verification. No fixtures created or deleted. Prices are eligible only when available, exact, ALLOWED, in product currency, and within the selected period." });
});

test("market overview remains tenant-scoped when given another tenant's product identifier", async ({}, testInfo) => {
  annotateEnabled(testInfo);
  const foreignProductId = process.env.MARKET_INTELLIGENCE_TEST_OTHER_TENANT_PRODUCT_ID;
  testInfo.skip(!foreignProductId, "BLOCKED: set MARKET_INTELLIGENCE_TEST_OTHER_TENANT_PRODUCT_ID to a product owned by a separate test tenant.");
  const result = await getOverview(foreignProductId, 30);
  testInfo.annotations.push({ type: "api", description: `GET /market-intelligence?productId=[other-tenant-product] HTTP ${result.response.status}` });
  expect(result.response.status).toBe(200);
  expect(result.body?.data?.selectedProduct?.id).not.toBe(foreignProductId);
  expect(result.body?.data?.products?.some((product: any) => product.id === foreignProductId)).toBe(false);
});

test("starter entitlement blocks the Market Intelligence API", async ({}, testInfo) => {
  const starterToken = process.env.MARKET_INTELLIGENCE_STARTER_ACCESS_TOKEN;
  testInfo.skip(!starterToken, "BLOCKED: set MARKET_INTELLIGENCE_STARTER_ACCESS_TOKEN for a disposable Starter tenant to run the entitlement regression check.");
  testInfo.annotations.push({ type: "mode", description: "starter-entitlement-regression" });
  const response = await fetch(`${apiBaseUrl}/market-intelligence?periodDays=30`, { headers: { Authorization: `Bearer ${starterToken}`, Accept: "application/json" } });
  testInfo.annotations.push({ type: "api", description: `GET /market-intelligence as Starter HTTP ${response.status}` });
  expect([401, 403]).toContain(response.status);
});
