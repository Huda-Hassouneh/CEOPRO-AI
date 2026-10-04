import test from "node:test";
import assert from "node:assert/strict";
import { buildTenantNotification } from "../../src/modules/tenant-notifications/tenant-notification.definition.js";
import type { TenantNotificationOutboxEvent } from "../../src/modules/tenant-notifications/tenant-notification.types.js";

function offerReadyEvent(
  overrides: Partial<TenantNotificationOutboxEvent> = {}
): TenantNotificationOutboxEvent {
  const now = new Date("2026-10-04T10:00:00.000Z");

  return {
    id: "11111111-1111-4111-8111-111111111111",
    tenant_id: "22222222-2222-4222-8222-222222222222",
    event_type: "CUSTOM_PLAN_OFFER_READY",
    dedupe_key:
      "custom-plan:offer-ready:33333333-3333-4333-8333-333333333333",
    payload: {
      quoteId: "33333333-3333-4333-8333-333333333333",
      quoteName: "Enterprise Custom",
      expiresAt: "2026-11-03T10:00:00.000Z"
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

test("CUSTOM_PLAN_OFFER_READY maps to an INFO billing notification", () => {
  const definition = buildTenantNotification(offerReadyEvent());

  assert.equal(definition.severity, "INFO");
  assert.equal(
    definition.titleKey,
    "tenantNotifications.customPlanOfferReady.title"
  );
  assert.equal(
    definition.bodyKey,
    "tenantNotifications.customPlanOfferReady.body"
  );
  assert.equal(definition.resourceType, "custom_plan_quote");
  assert.equal(
    definition.expiresAt?.toISOString(),
    "2026-11-03T10:00:00.000Z"
  );
  assert.equal(
    definition.resourceId,
    "33333333-3333-4333-8333-333333333333"
  );
  assert.deepEqual(definition.recipientPolicy, {
    requiredPermissions: ["manage_billing"],
    permissionMode: "ANY"
  });
});

test("CUSTOM_PLAN_OFFER_READY rejects malformed payloads", () => {
  const event = offerReadyEvent({
    payload: {
      quoteId: "",
      quoteName: "Enterprise Custom",
      expiresAt: null
    }
  });

  assert.throws(
    () => buildTenantNotification(event),
    /Invalid CUSTOM_PLAN_OFFER_READY payload/
  );
});

test("unsupported tenant notification events fail closed", () => {
  assert.throws(
    () =>
      buildTenantNotification(
        offerReadyEvent({ event_type: "UNKNOWN_EVENT" })
      ),
    /Unsupported tenant notification event: UNKNOWN_EVENT/
  );
});
