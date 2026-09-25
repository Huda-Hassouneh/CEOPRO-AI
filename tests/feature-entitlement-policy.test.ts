import assert from "node:assert/strict";
import test from "node:test";
import {
  getConsumptionBlockReason,
  hasRemainingCapacity
} from "../src/modules/features/service/entitlement-policy.js";

test("missing feature is blocked", () => {
  assert.equal(
    getConsumptionBlockReason({
      included: false,
      isUnlimited: false,
      isExceeded: false,
      aggregationType: "sum"
    }),
    "FEATURE_NOT_INCLUDED"
  );
});

test("SUM feature below quota is allowed", () => {
  assert.equal(
    getConsumptionBlockReason({
      included: true,
      isUnlimited: false,
      isExceeded: false,
      aggregationType: "sum"
    }),
    null
  );
});

test("SUM feature at quota is blocked as quota exhausted", () => {
  assert.equal(
    getConsumptionBlockReason({
      included: true,
      isUnlimited: false,
      isExceeded: true,
      aggregationType: "sum"
    }),
    "QUOTA_EXHAUSTED"
  );
});

test("MAX feature at capacity is blocked as capacity reached", () => {
  assert.equal(
    getConsumptionBlockReason({
      included: true,
      isUnlimited: false,
      isExceeded: true,
      aggregationType: "max"
    }),
    "CAPACITY_REACHED"
  );
});

test("unlimited feature is always consumable", () => {
  assert.equal(
    getConsumptionBlockReason({
      included: true,
      isUnlimited: true,
      isExceeded: true,
      aggregationType: "sum"
    }),
    null
  );
});


test("MAX capacity allows the last available slot", () => {
  assert.equal(hasRemainingCapacity({ currentUsage: 9, limit: 10 }), true);
});

test("MAX capacity blocks when full", () => {
  assert.equal(hasRemainingCapacity({ currentUsage: 10, limit: 10 }), false);
});

test("MAX capacity accounts for multi-unit additions", () => {
  assert.equal(
    hasRemainingCapacity({ currentUsage: 9, limit: 10, additionalAmount: 2 }),
    false
  );
});

test("deleting a resource frees MAX capacity immediately", () => {
  assert.equal(hasRemainingCapacity({ currentUsage: 10, limit: 10 }), false);
  assert.equal(hasRemainingCapacity({ currentUsage: 9, limit: 10 }), true);
});

test("unlimited MAX capacity always allows additions", () => {
  assert.equal(
    hasRemainingCapacity({ currentUsage: 1000000, limit: null, additionalAmount: 500 }),
    true
  );
});
