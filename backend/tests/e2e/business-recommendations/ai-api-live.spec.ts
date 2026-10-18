import { test, expect } from "@playwright/test";

const baseUrl = process.env.BUSINESS_RECOMMENDATIONS_AI_BASE_URL;
const token = process.env.BUSINESS_RECOMMENDATIONS_AI_TEST_TOKEN;
const tenantId = process.env.BUSINESS_RECOMMENDATIONS_AI_TEST_TENANT_ID;
const databaseUrl = process.env.AI_TEST_DATABASE_URL;
const databaseVerified = process.env.BUSINESS_RECOMMENDATIONS_AI_RUNTIME_DATABASE_VERIFIED === "1";
const liveEnabled = process.env.BUSINESS_RECOMMENDATIONS_LIVE_AI === "1";

function isLoopback(url?: string) {
  if (!url) return false;
  try {
    return ["127.0.0.1", "localhost", "::1"].includes(new URL(url).hostname);
  } catch {
    return false;
  }
}

function tokenClaims(value?: string): Record<string, unknown> | null {
  if (!value) return null;
  try {
    const part = value.split(".")[1];
    return part ? JSON.parse(Buffer.from(part, "base64url").toString("utf8")) : null;
  } catch {
    return null;
  }
}

function hasSafeDatabaseName(value?: string) {
  if (!value) return false;
  try {
    const name = decodeURIComponent(new URL(value).pathname.replace(/^\//, ""));
    return /(^|[-_])(test|testing|qa|e2e)([-_]|$)/i.test(name);
  } catch {
    return false;
  }
}

const claims = tokenClaims(token);
const ready = Boolean(
  liveEnabled && isLoopback(baseUrl) && token && tenantId && databaseVerified &&
  hasSafeDatabaseName(databaseUrl) && claims?.tenant_id === tenantId && claims?.user_id
);

test("live AI recommendation endpoint returns the real tenant-scoped response contract", async ({ request }, testInfo) => {
  testInfo.skip(!ready, "BLOCKED: enable local AI only after verifying its runtime DATABASE_URL is a dedicated test DB and provide a tenant JWT.");
  testInfo.annotations.push({ type: "mode", description: "opt-in-live-ai-api-contract; no Node subscription integration" });
  testInfo.annotations.push({ type: "tenant", description: tenantId! });
  testInfo.annotations.push({ type: "endpoint", description: "GET /dashboard/recommendations?limit=3" });
  testInfo.annotations.push({ type: "database-verification", description: "operator assertion BUSINESS_RECOMMENDATIONS_AI_RUNTIME_DATABASE_VERIFIED=1; API runtime cannot be independently inspected by this client" });

  const response = await request.get(`${baseUrl!.replace(/\/$/, "")}/dashboard/recommendations?limit=3`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" },
    timeout: 15_000
  });
  const body = await response.json().catch(() => null);
  testInfo.annotations.push({ type: "api", description: `GET /dashboard/recommendations?limit=3 HTTP ${response.status()}` });
  expect(response.status()).toBe(200);
  expect(body && Array.isArray(body.recommendations)).toBe(true);
  for (const recommendation of body.recommendations) {
    expect(Object.keys(recommendation).sort()).toEqual(["category", "message", "priority", "product_id"]);
    expect(typeof recommendation.product_id).toBe("string");
    expect(["Pricing", "Customer Feedback", "Demand", "Competitor Activity"]).toContain(recommendation.category);
    expect(["high", "medium", "low"]).toContain(recommendation.priority);
    expect(typeof recommendation.message).toBe("string");
  }
});
