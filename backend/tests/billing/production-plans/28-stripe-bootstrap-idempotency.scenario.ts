import test from "node:test";
import assert from "node:assert/strict";
import {
  assertProductionPlanTestEnvironment,
  disconnectProductionPlanDb,
  loadProductionPlans,
} from "./_production-plan-helpers.js";

assertProductionPlanTestEnvironment();

test("28.01 shared Stripe product bootstrap is fail-fast/idempotent and persists one product mapping", async () => {
  const { prisma, stripe, onBoardingService } = await loadProductionPlans();
  const previous = await prisma.appConfig.findUnique({ where: { key: "STRIPE_PRODUCT_ID" } });
  let createdProductId: string | null = null;
  try {
    await prisma.appConfig.deleteMany({ where: { key: "STRIPE_PRODUCT_ID" } });

    const first = await onBoardingService();
    assert.equal(first.success, true, "first bootstrap must create the shared Stripe product");
    const config = await prisma.appConfig.findUniqueOrThrow({ where: { key: "STRIPE_PRODUCT_ID" } });
    createdProductId = config.value;

    const product = await stripe.products.retrieve(config.value);
    assert.equal((product as any).deleted, undefined);
    assert.equal(product.name, "CEOPRO AI Platform");

    const second = await onBoardingService();
    assert.equal(second.success, false, "rerun must not create another shared product");
    assert.equal(second.code, "RESOURCE_ALREADY_EXISTS");

    const after = await prisma.appConfig.findUniqueOrThrow({ where: { key: "STRIPE_PRODUCT_ID" } });
    assert.equal(after.value, config.value, "Stripe product mapping must remain stable across reruns");
  } finally {
    if (createdProductId) {
      try { await stripe.products.update(createdProductId, { active: false }); } catch {}
    }
    if (previous) {
      await prisma.appConfig.upsert({
        where: { key: "STRIPE_PRODUCT_ID" },
        create: { key: "STRIPE_PRODUCT_ID", value: previous.value },
        update: { value: previous.value },
      });
    } else {
      await prisma.appConfig.deleteMany({ where: { key: "STRIPE_PRODUCT_ID" } });
    }
    await disconnectProductionPlanDb();
  }
});
