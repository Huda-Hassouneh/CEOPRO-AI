import test from "node:test";
import assert from "node:assert/strict";
import { grantsSubscriptionAccess } from "../src/constants/subscription.js";

test("active and trialing subscriptions grant entitlement access", () => {
  assert.equal(grantsSubscriptionAccess("active"), true);
  assert.equal(grantsSubscriptionAccess("trialing"), true);
});

test("non-access lifecycle states do not grant entitlement access", () => {
  for (const status of ["past_due", "pending", "payment_failed", "paused", "cancelled", "expired"]) {
    assert.equal(grantsSubscriptionAccess(status), false, status);
  }
});
