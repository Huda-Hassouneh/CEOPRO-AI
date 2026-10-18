import { expect, test } from "@playwright/test";

const token = process.env.MARKET_INTELLIGENCE_TEST_ACCESS_TOKEN;
const tenantId = process.env.MARKET_INTELLIGENCE_TEST_TENANT_ID;
const userId = process.env.MARKET_INTELLIGENCE_TEST_USER_ID;
const productId = process.env.AI_PRICING_TEST_PRODUCT_ID;
const frontendUrl = (process.env.MARKET_INTELLIGENCE_TEST_FRONTEND_URL || "http://127.0.0.1:5173").replace(/\/$/, "");
const configured = Boolean(token && tenantId && userId && productId);
test.skip(!configured, "BLOCKED: provide an authenticated disposable Market Intelligence test tenant and product to verify its localized UI.");

test("AI Pricing Generate and Refresh actions render Arabic labels in RTL mode", async ({ page }, testInfo) => {
  testInfo.annotations.push({ type: "mode", description: "authenticated-ai-pricing-arabic-ui-read-only" });
  testInfo.annotations.push({ type: "tenant", description: tenantId! });
  await page.addInitScript(({ accessToken, id, actor }) => {
    localStorage.setItem("ceopro_auth_session", JSON.stringify({ tenantId: id, user: { userId: actor }, roleKey: "owner", roles: ["owner"], accessToken }));
    localStorage.setItem("ceopro_locale", "ar");
  }, { accessToken: token!, id: tenantId!, actor: userId! });
  await page.goto(`${frontendUrl}/market`);
  await expect(page.locator(".market-intelligence-main")).toHaveAttribute("dir", "rtl");
  await page.locator(".market-main-product select").selectOption(productId!);
  await expect(page.getByRole("button", { name: /إنشاء توصية|اعادة توصية/ })).toBeVisible();
  testInfo.annotations.push({ type: "ui-metric", description: "Arabic AI Pricing action label is visible with RTL page direction; generation was not triggered." });
});
