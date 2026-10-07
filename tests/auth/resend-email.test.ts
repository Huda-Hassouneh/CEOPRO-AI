import assert from "node:assert/strict";
import test from "node:test";
import { sendVerificationEmail } from "../../src/integrations/email/resend.client.js";

test("Resend client sends a verification message using the configured API key", async (t) => {
  const originalKey = process.env.EMAIL_SERVICE_PROVIDER_API_KEY;
  const originalFrom = process.env.EMAIL_SERVICE_PROVIDER_FROM_EMAIL;
  const originalFrontendUrl = process.env.FRONTEND_URL;
  const originalFetch = globalThis.fetch;
  t.after(() => {
    if (originalKey === undefined) delete process.env.EMAIL_SERVICE_PROVIDER_API_KEY;
    else process.env.EMAIL_SERVICE_PROVIDER_API_KEY = originalKey;
    if (originalFrom === undefined) delete process.env.EMAIL_SERVICE_PROVIDER_FROM_EMAIL;
    else process.env.EMAIL_SERVICE_PROVIDER_FROM_EMAIL = originalFrom;
    if (originalFrontendUrl === undefined) delete process.env.FRONTEND_URL;
    else process.env.FRONTEND_URL = originalFrontendUrl;
    globalThis.fetch = originalFetch;
  });

  process.env.EMAIL_SERVICE_PROVIDER_API_KEY = "test-resend-key";
  process.env.EMAIL_SERVICE_PROVIDER_FROM_EMAIL = "CEO PRO <mail@example.com>";
  process.env.FRONTEND_URL = "https://app.example.com";
  let requestUrl = "";
  let requestInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    requestUrl = String(input);
    requestInit = init;
    return new Response("{}", { status: 200 });
  };

  await sendVerificationEmail({
    email: "owner@example.com",
    fullName: "Owner <script>",
    token: "e".repeat(64)
  });

  assert.equal(requestUrl, "https://api.resend.com/emails");
  assert.equal(new Headers(requestInit?.headers).get("authorization"), "Bearer test-resend-key");
  const body = JSON.parse(String(requestInit?.body));
  assert.deepEqual(body.to, ["owner@example.com"]);
  assert.equal(body.from, "CEO PRO <mail@example.com>");
  assert.match(body.html, /https:\/\/app\.example\.com\/verify-email\?token=/);
  assert.match(body.html, /&lt;script&gt;/);
});

test("Resend client fails clearly when its API key is not configured", async (t) => {
  const originalKey = process.env.EMAIL_SERVICE_PROVIDER_API_KEY;
  t.after(() => {
    if (originalKey === undefined) delete process.env.EMAIL_SERVICE_PROVIDER_API_KEY;
    else process.env.EMAIL_SERVICE_PROVIDER_API_KEY = originalKey;
  });
  delete process.env.EMAIL_SERVICE_PROVIDER_API_KEY;
  await assert.rejects(
    sendVerificationEmail({ email: "owner@example.com", token: "f".repeat(64) }),
    /EMAIL_SERVICE_PROVIDER_API_KEY is not configured/
  );
});
