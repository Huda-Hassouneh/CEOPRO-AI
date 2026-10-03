import test from "node:test";
import assert from "node:assert/strict";
import { buildPlatformNotification } from "../../src/modules/platform-notifications/platform-notification.definition.js";
import type { PlatformNotificationOutboxEvent } from "../../src/modules/platform-notifications/platform-notification.types.js";

function paymentFailedEvent(
  overrides: Partial<PlatformNotificationOutboxEvent> = {}
): PlatformNotificationOutboxEvent {
  const now = new Date("2026-10-03T14:29:02.332Z");

  return {
    id: "11111111-1111-4111-8111-111111111111",
    tenant_id: "22222222-2222-4222-8222-222222222222",
    event_type: "PAYMENT_FAILED",
    dedupe_key: "stripe:payment_failed:evt_test_123",
    payload: {
      subscriptionId: "33333333-3333-4333-8333-333333333333",
      stripeEventId: "evt_test_123",
      stripeInvoiceId: "in_test_123",
      paymentIntentId: "pi_test_123",
      failureReason: "Your card was declined."
    },
    status: "processing",
    attempts: 1,
    occurred_at: now,
    next_attempt_at: now,
    delivered_at: null,
    last_error_code: null,
    created_at: now,
    ...overrides
  };
}

test("PAYMENT_FAILED maps to a CRITICAL billing notification", () => {
  const definition = buildPlatformNotification(paymentFailedEvent());

  assert.equal(definition.severity, "CRITICAL");
  assert.equal(
    definition.titleKey,
    "platformNotifications.paymentFailed.title"
  );
  assert.equal(
    definition.bodyKey,
    "platformNotifications.paymentFailed.body"
  );
  assert.equal(definition.resourceType, "subscription");
  assert.equal(
    definition.resourceId,
    "33333333-3333-4333-8333-333333333333"
  );
  assert.deepEqual(definition.recipientPolicy, {
    requiredPermissions: ["billing.read"],
    permissionMode: "ANY"
  });
  assert.deepEqual(definition.payload, {
    stripeEventId: "evt_test_123",
    stripeInvoiceId: "in_test_123",
    paymentIntentId: "pi_test_123",
    failureReason: "Your card was declined."
  });
});

test("PAYMENT_FAILED accepts a null paymentIntentId", () => {
  const event = paymentFailedEvent({
    payload: {
      subscriptionId: "33333333-3333-4333-8333-333333333333",
      stripeEventId: "evt_test_123",
      stripeInvoiceId: "in_test_123",
      paymentIntentId: null,
      failureReason: "Payment collection failed"
    }
  });

  const definition = buildPlatformNotification(event);
  assert.equal(definition.payload.paymentIntentId, null);
});

test("PAYMENT_FAILED rejects malformed payloads instead of producing a bad notification", () => {
  const event = paymentFailedEvent({
    payload: {
      subscriptionId: "",
      stripeEventId: "evt_test_123",
      stripeInvoiceId: "in_test_123",
      paymentIntentId: null,
      failureReason: "Payment collection failed"
    }
  });

  assert.throws(
    () => buildPlatformNotification(event),
    /Invalid PAYMENT_FAILED payload/
  );
});

test("unsupported platform notification events fail closed", () => {
  assert.throws(
    () =>
      buildPlatformNotification(
        paymentFailedEvent({ event_type: "UNKNOWN_EVENT" })
      ),
    /Unsupported platform notification event: UNKNOWN_EVENT/
  );
});
