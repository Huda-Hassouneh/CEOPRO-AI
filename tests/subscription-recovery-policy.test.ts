import test from "node:test";
import assert from "node:assert/strict";
import { isRecoverableSubscriptionStatus } from "../src/modules/subscription/types/subscription-recovery.types.js";

test("payment-problem lifecycle states are recoverable", () => {
  for (const status of ["pending", "past_due", "payment_failed", "paused"]) {
    assert.equal(isRecoverableSubscriptionStatus(status), true, status);
  }
});

test("access-granting and terminal lifecycle states do not start recovery", () => {
  for (const status of ["active", "trialing", "cancelled", "canceled", "expired"]) {
    assert.equal(isRecoverableSubscriptionStatus(status), false, status);
  }
});
