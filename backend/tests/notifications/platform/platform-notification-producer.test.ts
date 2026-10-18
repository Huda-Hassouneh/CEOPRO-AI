import test from "node:test";
import assert from "node:assert/strict";
import type { Prisma } from "../../../src/generated/prisma/client.js";
import { platformNotificationProducer } from "../../../src/modules/platform-notifications/platform-notification.producer.js";

function fakeTransaction() {
  const calls: unknown[] = [];

  const tx = {
    platformNotificationOutbox: {
      async upsert(args: unknown) {
        calls.push(args);
        return { id: "outbox-1" };
      }
    }
  } as unknown as Prisma.TransactionClient;

  return { tx, calls };
}

test("paymentFailed writes a tenant-scoped idempotent outbox event", async () => {
  const { tx, calls } = fakeTransaction();

  await platformNotificationProducer.paymentFailed(tx, {
    tenantId: "22222222-2222-4222-8222-222222222222",
    subscriptionId: "33333333-3333-4333-8333-333333333333",
    stripeEventId: " evt_test_456 ",
    stripeInvoiceId: "in_test_456",
    paymentIntentId: "pi_test_456",
    failureReason: "Your card was declined."
  });

  assert.equal(calls.length, 1);

  const call = calls[0] as any;
  assert.deepEqual(call.where, {
    tenantId_dedupeKey: {
      tenantId: "22222222-2222-4222-8222-222222222222",
      dedupeKey: "stripe:payment_failed:evt_test_456"
    }
  });
  assert.deepEqual(call.update, {});
  assert.equal(call.create.eventType, "PAYMENT_FAILED");
  assert.equal(call.create.dedupeKey, "stripe:payment_failed:evt_test_456");
  assert.deepEqual(call.create.payload, {
    subscriptionId: "33333333-3333-4333-8333-333333333333",
    stripeEventId: "evt_test_456",
    stripeInvoiceId: "in_test_456",
    paymentIntentId: "pi_test_456",
    failureReason: "Your card was declined."
  });
  assert.ok(call.create.occurredAt instanceof Date);
});

test("paymentFailed refuses to create dedupe keys with an empty Stripe event id", async () => {
  const { tx, calls } = fakeTransaction();

  await assert.rejects(
    platformNotificationProducer.paymentFailed(tx, {
      tenantId: "22222222-2222-4222-8222-222222222222",
      subscriptionId: "33333333-3333-4333-8333-333333333333",
      stripeEventId: "   ",
      stripeInvoiceId: "in_test_456",
      paymentIntentId: null,
      failureReason: "Payment collection failed"
    }),
    /requires stripeEventId/
  );

  assert.equal(calls.length, 0);
});
