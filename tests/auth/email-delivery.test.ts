import assert from "node:assert/strict";
import test from "node:test";
import { createEmailDeliveryService } from "../../src/integrations/email/email.service.js";
import { createMimeMessage } from "../../src/integrations/email/gmail-smtp.client.js";

const input = {
  email: "customer@example.com",
  fullName: "Sam <script>alert(1)</script>",
  token: "a".repeat(64)
};

test("Gmail message is addressed to the signup email and contains safe UTF-8 alternatives", () => {
  const originalFrontendUrl = process.env.FRONTEND_URL;
  process.env.FRONTEND_URL = "https://app.example.com";
  try {
    const message = createMimeMessage(input, "tester@gmail.com");
    assert.match(message, /From: CEO PRO <tester@gmail\.com>/);
    assert.match(message, /To: <customer@example\.com>/);
    assert.match(message, /multipart\/alternative/);

    const sections = message.split("Content-Transfer-Encoding: base64\r\n\r\n");
    const textBody = Buffer.from(sections[1]?.split("\r\n--")[0] ?? "", "base64").toString("utf8");
    const htmlBody = Buffer.from(sections[2]?.split("\r\n--")[0] ?? "", "base64").toString("utf8");
    assert.match(textBody, /https:\/\/app\.example\.com\/verify-email\?token=/);
    assert.match(htmlBody, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
    assert.doesNotMatch(htmlBody, /<script>/);
  } finally {
    if (originalFrontendUrl === undefined) delete process.env.FRONTEND_URL;
    else process.env.FRONTEND_URL = originalFrontendUrl;
  }
});

test("email delivery dispatches to Gmail or Resend based on EMAIL_DELIVERY_PROVIDER", async (t) => {
  const originalProvider = process.env.EMAIL_DELIVERY_PROVIDER;
  t.after(() => {
    if (originalProvider === undefined) delete process.env.EMAIL_DELIVERY_PROVIDER;
    else process.env.EMAIL_DELIVERY_PROVIDER = originalProvider;
  });

  const called: string[] = [];
  const send = createEmailDeliveryService({
    gmail_smtp: async () => { called.push("gmail_smtp"); },
    resend: async () => { called.push("resend"); }
  });

  process.env.EMAIL_DELIVERY_PROVIDER = "gmail_smtp";
  await send(input);
  process.env.EMAIL_DELIVERY_PROVIDER = "resend";
  await send(input);

  assert.deepEqual(called, ["gmail_smtp", "resend"]);
});

test("email delivery rejects unknown providers instead of silently falling back", async (t) => {
  const originalProvider = process.env.EMAIL_DELIVERY_PROVIDER;
  t.after(() => {
    if (originalProvider === undefined) delete process.env.EMAIL_DELIVERY_PROVIDER;
    else process.env.EMAIL_DELIVERY_PROVIDER = originalProvider;
  });
  process.env.EMAIL_DELIVERY_PROVIDER = "unknown";

  await assert.rejects(
    createEmailDeliveryService()(input),
    /Unsupported EMAIL_DELIVERY_PROVIDER: unknown/
  );
});
