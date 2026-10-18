import test from "node:test";
import assert from "node:assert/strict";
import {
  calculateCustomPlanPrice,
  calculateExpectedProfitability,
} from "../../../src/modules/subscription/service/custom-plan-pricing.service.js";

const base = {
  quoteCurrency: "JOD",
  monthlyInfrastructureCost: 0,
  activePayingTenants: 1,
  estimatedOtherCost: 0,
  targetGrossMargin: 0,
};

test("02.01 gross-margin floor is cost / (1 - margin), not markup", () => {
  const result = calculateCustomPlanPrice({
    ...base,
    features: [],
    vendorRates: [],
    monthlyInfrastructureCost: 80,
    activePayingTenants: 10,
    estimatedOtherCost: 2,
    targetGrossMargin: 0.2,
    vendorCostRequiredFeatureIds: [],
  });

  assert.equal(result.estimatedTotalCost.toString(), "10");
  assert.equal(result.grossMarginFloor.toString(), "12.5");
  assert.equal(result.minimumSafePrice.toString(), "12.5");
});

test("02.02 vendor-cost ratio is calculated but not enforced by default", () => {
  const result = calculateCustomPlanPrice({
    ...base,
    features: [{ featureId: "ai", estimatedUsage: 10 }],
    vendorRates: [
      {
        id: "r1",
        featureId: "ai",
        vendor: "provider",
        service: "calls",
        billingUnit: "call",
        unitCost: 1,
        currency: "JOD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
      },
    ],
    targetGrossMargin: 0,
    maxVendorCostRevenueRatio: 0.2,
  });

  assert.equal(result.estimatedVendorCost.toString(), "10");
  assert.equal(result.vendorCostRatioFloor.toString(), "50");
  assert.equal(result.minimumSafePrice.toString(), "10");
  assert.equal(result.enforceVendorCostRatioFloor, false);
});

test("02.03 vendor-cost floor wins only when policy explicitly enables it", () => {
  const result = calculateCustomPlanPrice({
    ...base,
    features: [{ featureId: "ai", estimatedUsage: 10 }],
    vendorRates: [
      {
        id: "r1",
        featureId: "ai",
        vendor: "provider",
        service: "calls",
        billingUnit: "call",
        unitCost: 1,
        currency: "JOD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
      },
    ],
    maxVendorCostRevenueRatio: 0.2,
    enforceVendorCostRatioFloor: true,
  });

  assert.equal(result.minimumSafePrice.toString(), "50");
});

test("02.04 fixed platform fee is added after cost protection and rounded upward", () => {
  const result = calculateCustomPlanPrice({
    ...base,
    features: [],
    vendorRates: [],
    monthlyInfrastructureCost: 10,
    targetGrossMargin: 0.2,
    fixedPlatformFee: 5,
    roundingIncrement: 5,
    vendorCostRequiredFeatureIds: [],
  });

  assert.equal(result.minimumSafePrice.toString(), "12.5");
  assert.equal(result.recommendedPriceBeforeRounding.toString(), "17.5");
  assert.equal(result.recommendedPrice.toString(), "20");
});

test("02.05 non-vendor-backed feature is allowed without a vendor rate", () => {
  const result = calculateCustomPlanPrice({
    ...base,
    features: [{ featureId: "dashboard", estimatedUsage: 1 }],
    vendorRates: [],
    vendorCostRequiredFeatureIds: [],
  });

  assert.equal(result.estimatedVendorCost.toString(), "0");
});

test("02.06 vendor-backed feature with positive usage cannot silently price at zero", () => {
  assert.throws(
    () =>
      calculateCustomPlanPrice({
        ...base,
        features: [{ featureId: "rag", estimatedUsage: 1000 }],
        vendorRates: [],
        vendorCostRequiredFeatureIds: ["rag"],
      }),
    /Missing vendor rate/,
  );
});

test("02.07 negative usage is rejected", () => {
  assert.throws(
    () =>
      calculateCustomPlanPrice({
        ...base,
        features: [{ featureId: "x", estimatedUsage: -1 }],
        vendorRates: [],
        vendorCostRequiredFeatureIds: [],
      }),
    /Estimated usage cannot be negative/,
  );
});

test("02.08 active tenant count must be a positive integer", () => {
  assert.throws(
    () =>
      calculateCustomPlanPrice({
        ...base,
        features: [],
        vendorRates: [],
        activePayingTenants: 0,
      }),
    /activePayingTenants must be a positive integer/,
  );

  assert.throws(
    () =>
      calculateCustomPlanPrice({
        ...base,
        features: [],
        vendorRates: [],
        activePayingTenants: 1.5,
      }),
    /activePayingTenants must be a positive integer/,
  );
});

test("02.09 invalid margin and vendor-ratio policies are rejected", () => {
  assert.throws(
    () =>
      calculateCustomPlanPrice({
        ...base,
        features: [],
        vendorRates: [],
        targetGrossMargin: 1,
      }),
    /Invalid targetGrossMargin/,
  );

  assert.throws(
    () =>
      calculateCustomPlanPrice({
        ...base,
        features: [],
        vendorRates: [],
        maxVendorCostRevenueRatio: 0,
      }),
    /Invalid maxVendorCostRevenueRatio/,
  );
});

test("02.10 enabling vendor-cost floor without a ratio is rejected", () => {
  assert.throws(
    () =>
      calculateCustomPlanPrice({
        ...base,
        features: [],
        vendorRates: [],
        enforceVendorCostRatioFloor: true,
      }),
    /maxVendorCostRevenueRatio is required/,
  );
});

test("02.11 vendor operational multiplier and variability reserve are both applied", () => {
  const result = calculateCustomPlanPrice({
    ...base,
    features: [{ featureId: "x", estimatedUsage: 10 }],
    vendorRates: [
      {
        id: "r1",
        featureId: "x",
        vendor: "provider",
        service: "service",
        billingUnit: "unit",
        unitCost: 2,
        currency: "JOD",
        operationalMultiplier: 1.5,
        variabilityReserve: 1.2,
        verificationStatus: "confirmed",
      },
    ],
  });

  assert.equal(result.estimatedVendorCost.toString(), "36");
});

test("02.12 invalid vendor multiplier/reserve is rejected", () => {
  assert.throws(
    () =>
      calculateCustomPlanPrice({
        ...base,
        features: [{ featureId: "x", estimatedUsage: 1 }],
        vendorRates: [
          {
            id: "bad",
            featureId: "x",
            vendor: "provider",
            service: "service",
            billingUnit: "unit",
            unitCost: 1,
            currency: "JOD",
            operationalMultiplier: 0,
            variabilityReserve: 1,
            verificationStatus: "confirmed",
          },
        ],
      }),
    /Invalid multiplier/,
  );
});

test("02.13 unverified vendor rate produces a warning", () => {
  const result = calculateCustomPlanPrice({
    ...base,
    features: [{ featureId: "x", estimatedUsage: 1 }],
    vendorRates: [
      {
        id: "estimated",
        featureId: "x",
        vendor: "provider",
        service: "service",
        billingUnit: "unit",
        unitCost: 1,
        currency: "JOD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "estimated",
      },
    ],
  });

  assert.equal(result.warnings.length, 1);
  assert.match(result.warnings[0], /provider\/service rate is estimated/);
});

test("02.14 deprecated rates do not contribute to price", () => {
  const result = calculateCustomPlanPrice({
    ...base,
    features: [{ featureId: "x", estimatedUsage: 5 }],
    vendorRates: [
      {
        id: "old",
        featureId: "x",
        vendor: "provider",
        service: "old",
        billingUnit: "unit",
        unitCost: 999,
        currency: "JOD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "deprecated",
      },
    ],
    vendorCostRequiredFeatureIds: [],
  });

  assert.equal(result.estimatedVendorCost.toString(), "0");
});

test("02.15 profitability is derived from the final commercial price", () => {
  const result = calculateExpectedProfitability(20, 10, 4);

  assert.equal(result.expectedGrossMargin.toString(), "0.5");
  assert.equal(result.expectedVendorCostRatio.toString(), "0.2");
});

test("02.16 profitability rejects zero/negative selling price", () => {
  assert.throws(
    () => calculateExpectedProfitability(0, 10, 4),
    /finalPrice must be greater than zero/,
  );
});
