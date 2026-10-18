import { expect, test } from "@playwright/test";
import { DashboardDatabase } from "../../support/diagnostics/dashboard-db.js";

const enabled = process.env.AI_PRICING_RUN_LIVE_E2E === "1";
const token = process.env.MARKET_INTELLIGENCE_TEST_ACCESS_TOKEN;
const tenantId = process.env.MARKET_INTELLIGENCE_TEST_TENANT_ID;
const userId = process.env.MARKET_INTELLIGENCE_TEST_USER_ID;
const productId = process.env.AI_PRICING_TEST_PRODUCT_ID;
const dbUrl = process.env.MARKET_INTELLIGENCE_TEST_DATABASE_URL;
const tenantApproved = process.env.AI_PRICING_TEST_TENANT_APPROVED === "1";
const frontendUrl = (process.env.MARKET_INTELLIGENCE_TEST_FRONTEND_URL || "http://127.0.0.1:5173").replace(/\/$/, "");
const configured = enabled && tenantApproved && Boolean(token && tenantId && userId && productId && dbUrl);
test.skip(!configured, enabled
  ? "BLOCKED: configure and explicitly approve a disposable test tenant/product, user, token, and safe test database with provider-cost approval."
  : "BLOCKED: live E2E can call hosted Gradio and write recommendation evidence; opt in with AI_PRICING_RUN_LIVE_E2E=1.");

test("opt-in full frontend to Node to hosted Gradio pricing workflow persists evidence and preserves catalog price", async ({ page }, testInfo) => {
  testInfo.annotations.push({ type: "mode", description: "opt-in-full-frontend-node-hosted-gradio" });
  testInfo.annotations.push({ type: "tenant", description: tenantId! });
  testInfo.annotations.push({ type: "ai-dependency", description: "Real authenticated frontend request through Node to the configured hosted Gradio analytics/recommend API. No API response mocking." });

  const database = new DashboardDatabase(dbUrl!);
  try {
    const before = await database.getMarketIntelligenceFacts(tenantId!, userId!, productId!, 30);
    await page.addInitScript(({ accessToken, id, actor }) => {
      localStorage.setItem("ceopro_auth_session", JSON.stringify({ tenantId: id, user: { userId: actor }, roleKey: "owner", roles: ["owner"], accessToken }));
      localStorage.setItem("ceopro_locale", "en");
    }, { accessToken: token!, id: tenantId!, actor: userId! });
    await page.goto(`${frontendUrl}/market`);
    await expect(page.getByRole("heading", { name: "Market Intelligence", exact: true })).toBeVisible();
    const productSelect = page.locator(".market-main-product select");
    await productSelect.selectOption(productId!);
    const responsePromise = page.waitForResponse(response => response.url().includes("/features/pricing/recommend") && response.request().method() === "POST");
    await page.getByRole("button", { name: /Generate|Refresh/i }).click();
    const response = await responsePromise;
    testInfo.annotations.push({ type: "api", description: `POST /features/pricing/recommend HTTP ${response.status()}` });
    expect(response.status()).toBe(200);
    const payload = await response.json();
    const result = payload?.data ?? payload;
    expect(["OK", "UNKNOWN"]).toContain(result?.status);
    expect(result?.evidence_id).toBeTruthy();
    if (result.status === "OK") expect(result?.outcome_id).toBeTruthy();
    await expect(page.locator(".is-pricing")).toContainText(/Raise|Lower|Hold|Unknown|Unavailable|—/i);

    const persistence = await database.getPricingPersistenceFacts(tenantId!, userId!, result.evidence_id, result.outcome_id);
    expect(persistence.evidenceStored).toBe(true);
    expect(persistence.outcomeStored).toBe(result.status === "OK");
    const after = await database.getMarketIntelligenceFacts(tenantId!, userId!, productId!, 30);
    expect(after.productPrice).toBe(before.productPrice);
    testInfo.annotations.push({ type: "database-result", description: JSON.stringify({ evidenceStored: persistence.evidenceStored, outcomeStored: persistence.outcomeStored, productPriceUnchanged: before.productPrice === after.productPrice }) });
    testInfo.annotations.push({ type: "metric-check", description: `status=${result.status}; evidence/outcome persisted; catalog price before=${before.productPrice} after=${after.productPrice}` });
  } finally {
    await database.close();
  }
});
