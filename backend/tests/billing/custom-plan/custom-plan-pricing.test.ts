import test from "node:test";
import assert from "node:assert/strict";
import {
  calculateCustomPlanPrice,
  calculateExpectedProfitability
} from "../../../src/modules/subscription/service/custom-plan-pricing.service.js";

test("corrected PDF example keeps gross-margin and vendor-cost floors separate", () => {
  const result = calculateCustomPlanPrice({
    quoteCurrency: "USD",
    features: [
      { featureId: "social-comments", estimatedUsage: 300 },
      { featureId: "social-runs", estimatedUsage: 6 }
    ],
    vendorRates: [
      {
        id: "credits",
        featureId: "social-comments",
        vendor: "scrape_creators",
        service: "credits",
        billingUnit: "credit",
        unitCost: 0.002,
        currency: "USD",
        operationalMultiplier: 2,
        variabilityReserve: 1,
        verificationStatus: "confirmed"
      },
      {
        id: "apify",
        featureId: "social-runs",
        vendor: "apify",
        service: "compute_unit",
        billingUnit: "CU",
        unitCost: 0.2,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed"
      }
    ],
    monthlyInfrastructureCost: 400,
    activePayingTenants: 50,
    estimatedOtherCost: 0,
    targetGrossMargin: 0.2,
    maxVendorCostRevenueRatio: 0.2,
    enforceVendorCostRatioFloor: true,
  });

  assert.equal(result.estimatedVendorCost.toString(), "2.4");
  assert.equal(result.estimatedInfrastructureCost.toString(), "8");
  assert.equal(result.estimatedTotalCost.toString(), "10.4");
  assert.equal(result.grossMarginFloor.toString(), "13");
  assert.equal(result.vendorCostRatioFloor.toString(), "12");
  assert.equal(result.minimumSafePrice.toString(), "13");
});

test("automated flow does not force vendor-ratio floor unless policy enables it", () => {
  const result = calculateCustomPlanPrice({
    quoteCurrency: "JOD",
    features: [{ featureId: "ai", estimatedUsage: 1 }],
    vendorRates: [{
      id: "ai-rate",
      featureId: "ai",
      vendor: "ai-provider",
      service: "requests",
      billingUnit: "bundle",
      unitCost: 18,
      currency: "JOD",
      operationalMultiplier: 1,
      variabilityReserve: 1,
      verificationStatus: "confirmed",
    }],
    monthlyInfrastructureCost: 7,
    activePayingTenants: 1,
    estimatedOtherCost: 3,
    targetGrossMargin: 0.3,
    maxVendorCostRevenueRatio: 0.3,
    fixedPlatformFee: 5,
    roundingIncrement: 1,
  });

  assert.equal(result.estimatedTotalCost.toString(), "28");
  assert.equal(result.grossMarginFloor.toString(), "40");
  assert.equal(result.vendorCostRatioFloor.toString(), "60");
  assert.equal(result.minimumSafePrice.toString(), "40");
  assert.equal(result.recommendedPrice.toString(), "45");
  assert.equal(result.enforceVendorCostRatioFloor, false);
});

test("fixed platform fee is added after margin protection and rounded up", () => {
  const result = calculateCustomPlanPrice({
    quoteCurrency: "JOD",
    features: [],
    vendorRates: [],
    monthlyInfrastructureCost: 100,
    activePayingTenants: 10,
    estimatedOtherCost: 0,
    targetGrossMargin: 0.35,
    fixedPlatformFee: 25,
    roundingIncrement: 5,
    vendorCostRequiredFeatureIds: [],
  });

  assert.equal(result.estimatedTotalCost.toString(), "10");
  assert.equal(result.grossMarginFloor.toString(), "15.38");
  assert.equal(result.fixedPlatformFee.toString(), "25");
  assert.equal(result.recommendedPrice.toString(), "45");
});

test("platform-only feature can have positive quota without a vendor rate when not vendor-backed", () => {
  const result = calculateCustomPlanPrice({
    quoteCurrency: "JOD",
    features: [{ featureId: "team-members", estimatedUsage: 200 }],
    vendorRates: [],
    vendorCostRequiredFeatureIds: [],
    monthlyInfrastructureCost: 20,
    activePayingTenants: 10,
    estimatedOtherCost: 0,
    targetGrossMargin: 0.2,
  });
  assert.equal(result.estimatedVendorCost.toString(), "0");
  assert.equal(result.minimumSafePrice.toString(), "2.5");
});

test("vendor rate is normalized through an explicit quote-time FX rate", () => {
  const result = calculateCustomPlanPrice({
    quoteCurrency: "JOD",
    features: [{ featureId: "api", estimatedUsage: 10 }],
    vendorRates: [{
      id: "usd-rate",
      featureId: "api",
      vendor: "provider",
      service: "api",
      billingUnit: "call",
      unitCost: 1,
      currency: "USD",
      operationalMultiplier: 1,
      variabilityReserve: 1,
      verificationStatus: "confirmed"
    }],
    monthlyInfrastructureCost: 0,
    activePayingTenants: 1,
    estimatedOtherCost: 0,
    targetGrossMargin: 0,
    maxVendorCostRevenueRatio: 1,
    fxRate: 0.71,
    fxSourceCurrency: "USD",
    fxTargetCurrency: "JOD"
  });

  assert.equal(result.estimatedVendorCost.toString(), "7.1");
  assert.equal(result.minimumSafePrice.toString(), "7.1");
});

test("expected profitability is calculated from final commercial price", () => {
  const result = calculateExpectedProfitability(20, 10, 4);
  assert.equal(result.expectedGrossMargin.toString(), "0.5");
  assert.equal(result.expectedVendorCostRatio.toString(), "0.2");
});

test("invalid pricing policy ratios are rejected", () => {
  assert.throws(() => calculateCustomPlanPrice({
    quoteCurrency: "JOD",
    features: [],
    vendorRates: [],
    monthlyInfrastructureCost: 0,
    activePayingTenants: 1,
    estimatedOtherCost: 0,
    targetGrossMargin: 1,
    maxVendorCostRevenueRatio: 0.2
  }), /Invalid targetGrossMargin/);
});

test("vendor-backed positive usage cannot be silently priced without a vendor rate", () => {
  assert.throws(() => calculateCustomPlanPrice({
    quoteCurrency: "JOD",
    features: [{ featureId: "metered-feature", estimatedUsage: 10 }],
    vendorRates: [],
    vendorCostRequiredFeatureIds: ["metered-feature"],
    monthlyInfrastructureCost: 0,
    activePayingTenants: 1,
    estimatedOtherCost: 0,
    targetGrossMargin: 0.2,
    maxVendorCostRevenueRatio: 0.2
  }), /Missing vendor rate/);
});

test("competitor monitoring prices each vendor rate in its native unit", () => {
  const result = calculateCustomPlanPrice({
    quoteCurrency: "USD",
    features: [
      {
        featureId: "competitor-management",
        featureCode: "competitor_management",
        estimatedUsage: 1,
        configuration: {
          monitoringFrequencyMinutes: 10080,
          monitoringChecksPerMonth: 4,
        },
      },
      {
        featureId: "tracked-competitors",
        featureCode: "tracked_competitors",
        limitValue: 5,
        estimatedUsage: 5,
      },
    ],
    vendorRates: [
      {
        id: "compute-rate",
        featureId: "competitor-management",
        feature: { code: "competitor_management" },
        vendor: "collector",
        service: "browser-compute",
        billingUnit: "CU",
        unitCost: 0.2,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
        metadata: {
          usageAssumption: {
            model: "competitor_monitoring",
            unitsPerCompetitorCheck: 0.3,
          },
        },
      },
      {
        id: "credit-rate",
        featureId: "competitor-management",
        feature: { code: "competitor_management" },
        vendor: "search-provider",
        service: "search-credits",
        billingUnit: "credit",
        unitCost: 0.002,
        currency: "USD",
        operationalMultiplier: 2,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
        metadata: {
          usageAssumption: {
            model: "competitor_monitoring",
            unitsPerCompetitorCheck: 15,
          },
        },
      },
    ],
    vendorCostRequiredFeatureIds: ["competitor-management"],
    monthlyInfrastructureCost: 0,
    activePayingTenants: 1,
    estimatedOtherCost: 0,
    targetGrossMargin: 0,
  });

  assert.equal(result.estimatedVendorCost.toString(), "2.4");
  assert.deepEqual(
    result.vendorBreakdown.map((item) => [
      item.billingUnit,
      item.estimatedUsage,
    ]),
    [
      ["CU", "6"],
      ["credit", "300"],
    ],
  );
  assert.equal(
    result.vendorBreakdown[0].usageCalculation?.monitoringRunsPerMonth,
    "4",
  );
});

test("configured competitor monitoring requires a rate-specific usage assumption", () => {
  assert.throws(
    () =>
      calculateCustomPlanPrice({
        quoteCurrency: "USD",
        features: [
          {
            featureId: "competitor-management",
            featureCode: "competitor_management",
            estimatedUsage: 1,
            configuration: { monitoringFrequencyMinutes: 1440 },
          },
          {
            featureId: "tracked-competitors",
            featureCode: "tracked_competitors",
            limitValue: 5,
            estimatedUsage: 5,
          },
        ],
        vendorRates: [
          {
            id: "legacy-rate",
            featureId: "competitor-management",
            feature: { code: "competitor_management" },
            vendor: "collector",
            service: "compute",
            billingUnit: "CU",
            unitCost: 1,
            currency: "USD",
            operationalMultiplier: 1,
            variabilityReserve: 1,
            verificationStatus: "confirmed",
          },
        ],
        vendorCostRequiredFeatureIds: ["competitor-management"],
        monthlyInfrastructureCost: 0,
        activePayingTenants: 1,
        estimatedOtherCost: 0,
        targetGrossMargin: 0,
      }),
    /Missing competitor-monitoring usage assumption/,
  );
});
