import test from "node:test";
import assert from "node:assert/strict";
import {
  ACCESS_GRANTING_STATUSES,
  CURRENT_SUBSCRIPTION_STATUSES,
  grantsSubscriptionAccess,
} from "../../../src/constants/subscription.js";
import { mapStripeSubscriptionStatus } from "../../../src/utils/webhook.js";
import { isRecoverableSubscriptionStatus } from "../../../src/modules/subscription/types/subscription-recovery.types.js";

test("20.01 Stripe statuses map to explicit CEOPRO lifecycle states", () => {
  const cases = [
    ["trialing", "trialing"],
    ["active", "active"],
    ["past_due", "past_due"],
    ["canceled", "cancelled"],
    ["incomplete", "pending"],
    ["incomplete_expired", "expired"],
    ["unpaid", "payment_failed"],
    ["paused", "paused"],
  ] as const;

  for (const [stripeStatus, expected] of cases) {
    assert.equal(mapStripeSubscriptionStatus(stripeStatus), expected, stripeStatus);
  }
});

test("20.02 only active and trialing grant subscription access", () => {
  assert.deepEqual([...ACCESS_GRANTING_STATUSES], ["active", "trialing"]);
  for (const status of ["active", "trialing"]) {
    assert.equal(grantsSubscriptionAccess(status), true, status);
  }
  for (const status of [
    "pending",
    "past_due",
    "payment_failed",
    "paused",
    "cancelled",
    "expired",
  ]) {
    assert.equal(grantsSubscriptionAccess(status), false, status);
  }
});

test("20.03 recoverable statuses remain current but do not grant access", () => {
  for (const status of ["pending", "past_due", "payment_failed", "paused"]) {
    assert.equal(isRecoverableSubscriptionStatus(status), true, status);
    assert.ok(CURRENT_SUBSCRIPTION_STATUSES.includes(status as any), status);
    assert.equal(grantsSubscriptionAccess(status), false, status);
  }
});

test("20.04 cancelled and expired are terminal, not current/recoverable", () => {
  for (const status of ["cancelled", "expired"]) {
    assert.equal(CURRENT_SUBSCRIPTION_STATUSES.includes(status as any), false, status);
    assert.equal(isRecoverableSubscriptionStatus(status), false, status);
  }
});
