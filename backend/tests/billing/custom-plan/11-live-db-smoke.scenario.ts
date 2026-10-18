import test from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";

const testDatabaseUrl = process.env.CUSTOM_PLAN_TEST_DATABASE_URL?.trim();

if (testDatabaseUrl) {
  // Must happen before importing CEOPRO's Prisma singleton.
  process.env.DATABASE_URL = testDatabaseUrl;
}

test(
  "11.01 live DB: tenant isolation + atomic quote conversion + feature persistence",
  { skip: !testDatabaseUrl ? "Set CUSTOM_PLAN_TEST_DATABASE_URL to a disposable migrated database." : false },
  async () => {
    const [{ prisma }, { default: customPlanRepository }, { default: plansRepo }] =
      await Promise.all([
        import("../../../src/config/database.js"),
        import("../../../src/modules/subscription/repo/custom-plan.repo.js"),
        import("../../../src/modules/subscription/repo/plans.repo.js"),
      ]);

    const run = randomUUID().slice(0, 8);
    let tenantAId: string | null = null;
    let tenantBId: string | null = null;
    let featureId: string | null = null;
    let quoteId: string | null = null;
    let planId: string | null = null;

    try {
      const [tenantA, tenantB] = await Promise.all([
        prisma.company.create({
          data: {
            businessName: `CP Test A ${run}`,
            businessType: "test",
            countryCode: "JO",
            primaryCurrency: "JOD",
          },
        }),
        prisma.company.create({
          data: {
            businessName: `CP Test B ${run}`,
            businessType: "test",
            countryCode: "JO",
            primaryCurrency: "JOD",
          },
        }),
      ]);
      tenantAId = tenantA.id;
      tenantBId = tenantB.id;

      const feature = await prisma.feature.create({
        data: {
          code: `cp_test_${run}`,
          name: `Custom Plan Test ${run}`,
          name_ar: `Custom Plan Test ${run}`,
          type: "limit",
          unit: "count",
          unit_ar: "count",
          aggregationType: "sum",
          resetCycle: "billing_period",
        },
      });
      featureId = feature.id;

      const quote = await customPlanRepository.createQuote({
        tenantId: tenantA.id,
        data: {
          name: `Test ${run}`,
          nameAr: `Test ${run}`,
          status: "approved",
          currency: "JOD",
          billingIntervalValue: 1,
          billingIntervalUnit: "month",
          trialPeriodValue: 0,
          billingOptions: [
            {
              period: "monthly",
              months: 1,
              discountPercent: 0,
            },
          ],
          estimatedVendorCost: 1,
          estimatedInfrastructureCost: 1,
          estimatedOtherCost: 0,
          estimatedTotalCost: 2,
          targetGrossMargin: 0.2,
          maxVendorCostRevenueRatio: 0.2,
          grossMarginFloor: 2.5,
          vendorCostRatioFloor: 5,
          minimumSafePrice: 2.5,
          finalPrice: 10,
          pricingInputs: { test: true },
          pricingSnapshot: { test: true },
          expiresAt: new Date(Date.now() + 60_000),
        },
        features: [
          {
            featureId: feature.id,
            limitValue: 25,
            estimatedUsage: 25,
            metadata: {
              source: "automated-test",
              configuration: { testMode: true },
            },
          },
        ],
      });
      quoteId = quote.id;

      const visibleToA = await customPlanRepository.findQuoteForTenant(
        quote.id,
        tenantA.id,
      );
      const visibleToB = await customPlanRepository.findQuoteForTenant(
        quote.id,
        tenantB.id,
      );

      assert.equal(visibleToA?.id, quote.id);
      assert.equal(visibleToB, null);

      const attempts = await Promise.all([
        customPlanRepository.convertQuoteToPlan({
          quoteId: quote.id,
          tenantId: tenantA.id,
          paymentProviderProductId: `prod_test_${run}`,
          paymentProviderPlanId: `price_test_${run}_a`,
          billingOptions: [
            {
              period: "monthly",
              months: 1,
              discountPercent: 0,
              stripePriceId: `price_test_${run}_a`,
            },
          ],
        }),
        customPlanRepository.convertQuoteToPlan({
          quoteId: quote.id,
          tenantId: tenantA.id,
          paymentProviderProductId: `prod_test_${run}`,
          paymentProviderPlanId: `price_test_${run}_b`,
          billingOptions: [
            {
              period: "monthly",
              months: 1,
              discountPercent: 0,
              stripePriceId: `price_test_${run}_b`,
            },
          ],
        }),
      ]);

      const winners = attempts.filter(Boolean);
      assert.equal(winners.length, 1, "exactly one concurrent conversion must win");

      const plan = winners[0]!;
      planId = plan.id;

      assert.equal(plan.planType, "custom");
      assert.equal(plan.tenantId, tenantA.id);
      assert.equal(Number(plan.price), 10);
      assert.equal(plan.planFeatures.length, 1);
      assert.equal(plan.planFeatures[0].limit_value, 25);
      assert.deepEqual(plan.planFeatures[0].metadata, {
        source: "automated-test",
        configuration: { testMode: true },
      });

      const wrongTenantConversion = await customPlanRepository.convertQuoteToPlan({
        quoteId: quote.id,
        tenantId: tenantB.id,
        paymentProviderProductId: `prod_test_${run}`,
        paymentProviderPlanId: `price_test_${run}_wrong`,
        billingOptions: [],
      });
      assert.equal(wrongTenantConversion, null);

      const publicPlans = await plansRepo.getActivePlansWithLimits();
      assert.equal(
        publicPlans.some((candidate) => candidate.id === plan.id),
        false,
        "tenant-private custom plan must never appear in the public standard-plan list",
      );
    } finally {
      if (planId) {
        await prisma.plan.deleteMany({ where: { id: planId } });
      }
      if (quoteId) {
        await prisma.customPlanQuote.deleteMany({ where: { id: quoteId } });
      }
      if (featureId) {
        await prisma.feature.deleteMany({ where: { id: featureId } });
      }
      const companyIds = [tenantAId, tenantBId].filter(
        (value): value is string => Boolean(value),
      );
      if (companyIds.length) {
        await prisma.company.deleteMany({ where: { id: { in: companyIds } } });
      }
      await prisma.$disconnect();
    }
  },
);
