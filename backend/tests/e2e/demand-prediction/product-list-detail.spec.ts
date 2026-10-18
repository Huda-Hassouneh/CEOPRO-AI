import { test, expect } from "@playwright/test";

const token = process.env.DEMAND_PREDICTION_TEST_ACCESS_TOKEN;
const tenantId = process.env.DEMAND_PREDICTION_TEST_TENANT_ID;
const userId = process.env.DEMAND_PREDICTION_TEST_USER_ID;
const apiBaseUrl = (process.env.DEMAND_PREDICTION_TEST_API_URL || "http://127.0.0.1:5000").replace(/\/$/, "");
const frontendUrl = (process.env.DEMAND_PREDICTION_TEST_FRONTEND_URL || "http://127.0.0.1:5173").replace(/\/$/, "");
const enabled = Boolean(token && tenantId && userId);
if (!enabled) test.skip(true, "BLOCKED: configure the dedicated Demand Prediction test tenant, user, and access token.");

function productName(name: any) {
  if (typeof name === "string") return name;
  return name?.en || name?.ar || "";
}

test("product search, filters, pagination, detail route, and detail data follow the real API", async ({ page }, testInfo) => {
  test.skip(!enabled, "BLOCKED: set DEMAND_PREDICTION_TEST_ACCESS_TOKEN, DEMAND_PREDICTION_TEST_TENANT_ID, and DEMAND_PREDICTION_TEST_USER_ID.");
  testInfo.annotations.push({ type: "mode", description: "authenticated-demand-prediction-product-list-detail" });
  testInfo.annotations.push({ type: "tenant", description: tenantId! });
  const browserErrors: string[] = [];
  page.on("pageerror", error => browserErrors.push(error.message));
  page.on("console", message => { if (message.type() === "error") browserErrors.push(message.text()); });
  page.on("requestfailed", request => browserErrors.push(`${request.method()} ${new URL(request.url()).pathname}: ${request.failure()?.errorText}`));
  const overviewResponse = await fetch(`${apiBaseUrl}/forecasting/demand?periodDays=30&productId=all`, { headers: { Authorization: `Bearer ${token}`, Accept: "application/json" } });
  expect(overviewResponse.status).toBe(200);
  const overview = (await overviewResponse.json()).data;

  await page.addInitScript(({ accessToken, id, actor }) => {
    localStorage.setItem("ceopro_auth_session", JSON.stringify({ tenantId: id, user: { userId: actor }, roleKey: "owner", roles: ["owner"], accessToken }));
    localStorage.setItem("ceopro_locale", "en");
  }, { accessToken: token!, id: tenantId!, actor: userId! });
  await page.goto(`${frontendUrl}/demand/products`);
  await expect(page.getByRole("heading", { name: "Product Forecasts", exact: true })).toBeVisible();
  const search = page.getByRole("textbox", { name: "Search products..." });
  const product = overview.forecasts?.find((candidate: any) => {
    const candidateName = productName(candidate.name);
    return candidateName && overview.forecasts.filter((row: any) => productName(row.name) === candidateName).length === 1;
  });
  if (product) {
    const name = productName(product.name);
    test.skip(!name, "BLOCKED: current product has no English or Arabic display name.");
    await search.fill(name);
    const matchingRows = page.locator(".demand-products-table tbody tr");
    await expect(matchingRows).toHaveCount(1);
    await expect(matchingRows.first()).toContainText(name);

    const category = page.getByRole("combobox", { name: "Category" });
    const categoryOption = await category.locator("option").nth(1).getAttribute("value");
    if (categoryOption) {
      await category.selectOption(categoryOption);
      await expect(category).toHaveValue(categoryOption);
    }
    const trend = page.getByRole("combobox", { name: "Forecast Trend" });
    await trend.selectOption("increasing");
    await trend.selectOption("all");
    testInfo.annotations.push({ type: "filter-check", description: "Search found one source product; category and trend filters accepted real options." });
    await page.getByRole("button", { name: "Clear Filters" }).click();
  } else {
    if (overview.forecasts?.length) test.skip(true, "BLOCKED: test tenant has no uniquely named product row for reliable detail navigation.");
    await expect(page.getByText("No product forecasts match these filters.", { exact: true })).toBeVisible();
    testInfo.annotations.push({ type: "empty-state", description: "No forecast product rows; list displayed the configured empty state." });
  }

  const pageSize = 20;
  const next = page.getByRole("button", { name: "Next page" });
  if ((overview.forecasts?.length ?? 0) <= pageSize) {
    await expect(next).toBeDisabled();
  } else {
    await expect(next).toBeEnabled();
    await next.click();
    await expect(page.locator(".demand-pagination .is-active")).toHaveText("2");
  }
  testInfo.annotations.push({ type: "pagination-check", description: `product count=${overview.forecasts?.length ?? 0}; page size=${pageSize}; next page state verified` });

  if (product) {
    const name = productName(product.name);
    await search.fill(name);
    const matchingRows = page.locator(".demand-products-table tbody tr");
    await expect(matchingRows).toHaveCount(1);
    const detailResponse = page.waitForResponse(response => response.url().includes(`/forecasting/demand/${product.id}`));
    await matchingRows.getByRole("button", { name: "View Details" }).click();
    expect((await detailResponse).status()).toBe(200);
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
    await expect(page.locator(".demand-approved-detail")).toBeVisible();
    testInfo.annotations.push({ type: "api", description: `GET /forecasting/demand/[selected-product] HTTP 200` });
  }
  expect(browserErrors).toEqual([]);
});
