import test from "node:test";
import assert from "node:assert/strict";
import {
  assertProductionPlanTestEnvironment,
  cleanupStandardPlanFixture,
  createStandardPlanFixture,
  disconnectProductionPlanDb,
  loadProductionPlans,
} from "./_production-plan-helpers.js";

assertProductionPlanTestEnvironment();

test("30.01 public catalog shows active standard plan while managed catalog retains inactive standard plans", async () => {
  const active = await createStandardPlanFixture({ planNamePrefix: "Catalog Active", active: true });
  const inactive = await createStandardPlanFixture({ planNamePrefix: "Catalog Inactive", active: false });
  try {
    const { getPlans, getManagedStandardPlans } = await loadProductionPlans();
    const publicCatalog = await getPlans();
    const managedCatalog = await getManagedStandardPlans();
    const publicIds = new Set(publicCatalog.map((plan: any) => plan.id));
    const managedIds = new Set(managedCatalog.map((plan: any) => plan.id));

    assert.equal(publicIds.has(active.planId), true);
    assert.equal(publicIds.has(inactive.planId), false);
    assert.equal(managedIds.has(active.planId), true);
    assert.equal(managedIds.has(inactive.planId), true);
  } finally {
    // Cleanup in reverse creation order so the shared Stripe product AppConfig
    // is restored to the exact value that existed before this test.
    await cleanupStandardPlanFixture(inactive);
    await cleanupStandardPlanFixture(active);
    await disconnectProductionPlanDb();
  }
});
