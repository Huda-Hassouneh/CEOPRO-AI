import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

async function source(path: string) {
  return readFile(new URL(path, import.meta.url), "utf8");
}

test("Stripe invoice.payment_failed propagates Stripe event.id to the handler", async () => {
  const code = await source(
    "../../src/modules/subscription/service/stripe-webhook.service.ts"
  );

  assert.match(code, /case\s+["']invoice\.payment_failed["']/);
  assert.match(
    code,
    /handleInvoicePaymentFailed\s*\(\s*event\.data\.object\s+as\s+Stripe\.Invoice\s*,\s*event\.id\s*\)/s
  );
});

test("failed payment persistence and notification outbox write share one transaction", async () => {
  const code = await source("../../src/utils/webhook handlers.ts");

  const transactionStart = code.indexOf("await prisma.$transaction(async (tx) => {");
  const paymentWrite = code.indexOf("webhookRepo.createInvoicePayment", transactionStart);
  const notificationWrite = code.indexOf(
    "platformNotificationProducer.paymentFailed(tx",
    transactionStart
  );
  const transactionEnd = code.indexOf("});", notificationWrite);

  assert.ok(transactionStart >= 0, "payment-failed transaction must exist");
  assert.ok(paymentWrite > transactionStart, "payment write must be inside transaction");
  assert.ok(
    notificationWrite > paymentWrite,
    "notification outbox write must be inside the same transaction"
  );
  assert.ok(transactionEnd > notificationWrite, "transaction must close after both writes");
  assert.match(code.slice(notificationWrite, transactionEnd), /stripeEventId/);
});

test("notification HTTP routes expose the five recipient-scoped operations", async () => {
  const code = await source(
    "../../src/modules/platform-notifications/route/platform-notification.route.ts"
  );

  for (const route of [
    'router.get(\n  "/notifications"',
    'router.get(\n  "/notifications/unread-count"',
    'router.post(\n  "/notifications/read-all"',
    'router.post(\n  "/notifications/:id/read"',
    'router.post(\n  "/notifications/:id/archive"'
  ]) {
    assert.ok(code.includes(route), `missing route contract: ${route}`);
  }

  assert.match(
    code,
    /requirePlatformPermission\(["']notifications\.read["']\)/
  );
});

test("dispatcher uses the dedicated worker Prisma client", async () => {
  const code = await source(
    "../../src/modules/platform-notifications/platform-notification.dispatcher.ts"
  );

  assert.match(code, /notificationWorkerPrisma\.\$transaction/);
  assert.doesNotMatch(code, /\bprisma\.\$transaction/);
});

test("worker connection is sourced only from NOTIFICATION_WORKER_DATABASE_URL", async () => {
  const code = await source(
    "../../src/config/notification-worker-database.ts"
  );

  assert.match(code, /NOTIFICATION_WORKER_DATABASE_URL/);
  assert.doesNotMatch(code, /getRequiredEnv\(["']DATABASE_URL["']\)/);
});
