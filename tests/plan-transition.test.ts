import assert from "node:assert/strict";
import test from "node:test";
import { analyzePlanTransition } from "../src/modules/subscription/service/plan-transition.service.js";

const feature = (id: string, limit: number | null) => ({
  feature_id: id,
  limit_value: limit,
  feature: { id, code: id, name: id }
});

const plan = (id: string, features: ReturnType<typeof feature>[]) => ({
  id,
  name: id,
  planFeatures: features
});

test("gain-only transition is an immediate entitlement upgrade even if price may be lower", () => {
  const result = analyzePlanTransition(
    plan("pro", [feature("documents", 10_000), feature("ai", 2_000)]),
    plan("custom", [
      feature("documents", 20_000),
      feature("ai", 5_000),
      feature("reports", null)
    ])
  );

  assert.equal(result.type, "upgrade");
  assert.equal(result.recommendedEffectiveTiming, "immediate");
  assert.equal(result.hasEntitlementLoss, false);
  assert.equal(result.gains.length, 3);
});

test("any entitlement loss schedules the target for period end", () => {
  const result = analyzePlanTransition(
    plan("pro", [feature("documents", 20_000), feature("ai", 5_000)]),
    plan("custom", [feature("documents", 10_000), feature("ai", 5_000)])
  );

  assert.equal(result.type, "downgrade");
  assert.equal(result.recommendedEffectiveTiming, "period_end");
  assert.equal(result.hasEntitlementLoss, true);
});

test("mixed transition is explicit and uses period-end timing", () => {
  const result = analyzePlanTransition(
    plan("pro", [feature("documents", 10_000), feature("ai", 5_000)]),
    plan("custom", [feature("documents", 20_000), feature("ai", 2_000)])
  );

  assert.equal(result.type, "mixed");
  assert.equal(result.recommendedEffectiveTiming, "period_end");
  assert.equal(result.hasEntitlementGain, true);
  assert.equal(result.hasEntitlementLoss, true);
});

test("limited to unlimited is a gain and unlimited to limited is a loss", () => {
  const gain = analyzePlanTransition(
    plan("limited", [feature("documents", 1_000)]),
    plan("unlimited", [feature("documents", null)])
  );
  const loss = analyzePlanTransition(
    plan("unlimited", [feature("documents", null)]),
    plan("limited", [feature("documents", 1_000)])
  );

  assert.equal(gain.type, "upgrade");
  assert.equal(loss.type, "downgrade");
});

test("removed feature is a loss and added feature is a gain", () => {
  const removed = analyzePlanTransition(
    plan("a", [feature("reports", null)]),
    plan("b", [])
  );
  const added = analyzePlanTransition(
    plan("a", []),
    plan("b", [feature("reports", null)])
  );

  assert.equal(removed.type, "downgrade");
  assert.equal(added.type, "upgrade");
});

test("identical entitlements are equivalent", () => {
  const result = analyzePlanTransition(
    plan("a", [feature("documents", 10_000), feature("reports", null)]),
    plan("b", [feature("documents", 10_000), feature("reports", null)])
  );

  assert.equal(result.type, "equivalent");
  assert.equal(result.recommendedEffectiveTiming, "immediate");
});

test("legacy plans with no configured entitlements are marked non-comparable", () => {
  const result = analyzePlanTransition(plan("a", []), plan("b", []));

  assert.equal(result.comparable, false);
  assert.equal(result.type, "equivalent");
});
