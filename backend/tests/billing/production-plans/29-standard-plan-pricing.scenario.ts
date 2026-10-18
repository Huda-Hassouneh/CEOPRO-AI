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

test("29.01 standard plan creates stable DB ↔ Stripe price mappings for monthly/yearly options", async () => {
  const fixture = await createStandardPlanFixture({ basePriceUsd: 20, limitValue: 250 });
  try {
    const { prisma, stripe } = await loadProductionPlans();
    const plan = await prisma.plan.findUniqueOrThrow({
      where: { id: fixture.planId },
      include: { priceVersions: true, planFeatures: true },
    });

    assert.equal(plan.planType, "standard");
    assert.equal(plan.tenantId, null);
    assert.equal(plan.currency, "USD");
    assert.equal(plan.priceVersions.length, 2);
    assert.equal(plan.planFeatures.length, 1);

    const options = plan.billingOptions as Array<any>;
    const monthly = options.find((option) => option.period === "monthly");
    const yearly = options.find((option) => option.period === "yearly");
    assert.ok(monthly?.stripePriceId);
    assert.ok(yearly?.stripePriceId);

    const monthlyPrice = await stripe.prices.retrieve(monthly.stripePriceId);
    const yearlyPrice = await stripe.prices.retrieve(yearly.stripePriceId);
    assert.equal(monthlyPrice.currency, "usd");
    assert.equal(monthlyPrice.unit_amount, 2000);
    assert.equal(monthlyPrice.recurring?.interval, "month");
    assert.equal(monthlyPrice.recurring?.interval_count, 1);
    assert.equal(yearlyPrice.currency, "usd");
    assert.equal(yearlyPrice.unit_amount, 21600, "20 × 12 × 90% = 216 USD/year");
    assert.equal(yearlyPrice.recurring?.interval, "year");
    assert.equal(yearlyPrice.recurring?.interval_count, 1);
  } finally {
    await cleanupStandardPlanFixture(fixture);
    await disconnectProductionPlanDb();
  }
});
