import test from "node:test";
import assert from "node:assert/strict";
import type { Prisma } from "../../../src/generated/prisma/client.js";
import { tenantNotificationProducer } from "../../../src/modules/tenant-notifications/tenant-notification.producer.js";

function fakeTransaction() {
  const calls: unknown[] = [];

  const tx = {
    tenantNotificationOutbox: {
      async createMany(args: unknown) {
        calls.push(args);
        return { count: 1 };
      }
    }
  } as unknown as Prisma.TransactionClient;

  return { tx, calls };
}

test("customPlanOfferReady writes a tenant-scoped idempotent outbox event", async () => {
  const { tx, calls } = fakeTransaction();

  await tenantNotificationProducer.customPlanOfferReady(tx, {
    tenantId: "22222222-2222-4222-8222-222222222222",
    quoteId: " 33333333-3333-4333-8333-333333333333 ",
    quoteName: "Enterprise Custom",
    expiresAt: new Date("2026-11-03T10:00:00.000Z")
  });

  assert.equal(calls.length, 1);

  const call = calls[0] as any;
  assert.equal(call.skipDuplicates, true);
  assert.equal(call.data.length, 1);
  const created = call.data[0];
  assert.equal(created.tenantId, "22222222-2222-4222-8222-222222222222");
  assert.equal(created.eventType, "CUSTOM_PLAN_OFFER_READY");
  assert.equal(
    created.dedupeKey,
    "custom-plan:offer-ready:33333333-3333-4333-8333-333333333333"
  );
  assert.deepEqual(created.payload, {
    quoteId: "33333333-3333-4333-8333-333333333333",
    quoteName: "Enterprise Custom",
    expiresAt: "2026-11-03T10:00:00.000Z"
  });
  assert.ok(created.occurredAt instanceof Date);
});

test("customPlanOfferReady refuses an empty quote id", async () => {
  const { tx, calls } = fakeTransaction();

  await assert.rejects(
    tenantNotificationProducer.customPlanOfferReady(tx, {
      tenantId: "22222222-2222-4222-8222-222222222222",
      quoteId: "   ",
      quoteName: "Enterprise Custom",
      expiresAt: null
    }),
    /requires quoteId/
  );

  assert.equal(calls.length, 0);
});
