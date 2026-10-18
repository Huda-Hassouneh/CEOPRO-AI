import test from "node:test";
import assert from "node:assert/strict";
import { calculateCustomPlanPrice } from "../../../src/modules/subscription/service/custom-plan-pricing.service.js";

const common = {
  quoteCurrency: "USD",
  vendorRates: [],
  vendorCostRequiredFeatureIds: [],
  monthlyInfrastructureCost: 0,
  activePayingTenants: 1,
  estimatedOtherCost: 0,
  targetGrossMargin: 0,
};

test("04.01 document storage MB converts to GB-month before pricing", () => {
  const result = calculateCustomPlanPrice({
    ...common,
    features: [
      {
        featureId: "storage",
        featureCode: "document_storage_mb",
        limitValue: 1024,
        estimatedUsage: 1024,
      },
    ],
    infrastructureRates: [
      {
        id: "storage-rate",
        featureId: "storage",
        feature: { code: "document_storage_mb" },
        costDriver: "document-storage",
        usageBasis: "limit_value",
        billingUnit: "GB-month",
        billingUnitsPerFeatureUnit: 0.0009765625,
        unitCost: 0.02,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
      },
    ],
  });

  assert.equal(result.usageDrivenInfrastructureCost.toString(), "0.02");
  assert.equal(
    result.infrastructureBreakdown[0].normalizedBillableQuantity,
    "1",
  );
  assert.equal(result.infrastructureBreakdown[0].cost, "0.02");
});

test("04.02 estimated_usage basis prices estimated usage, not configured limit", () => {
  const result = calculateCustomPlanPrice({
    ...common,
    features: [
      {
        featureId: "extract",
        limitValue: 10000,
        estimatedUsage: 2500,
      },
    ],
    infrastructureRates: [
      {
        id: "extract-rate",
        featureId: "extract",
        costDriver: "document-extraction",
        usageBasis: "estimated_usage",
        billingUnit: "KB",
        billingUnitsPerFeatureUnit: 1,
        unitCost: 0.001,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
      },
    ],
  });

  assert.equal(
    result.infrastructureBreakdown[0].originalFeatureQuantity,
    "2500",
  );
  assert.equal(result.usageDrivenInfrastructureCost.toString(), "2.5");
});

test("04.03 enabled_feature basis charges exactly one feature unit", () => {
  const result = calculateCustomPlanPrice({
    ...common,
    features: [{ featureId: "analytics", estimatedUsage: 999 }],
    infrastructureRates: [
      {
        id: "analytics-rate",
        featureId: "analytics",
        costDriver: "analytics-runtime",
        usageBasis: "enabled_feature",
        billingUnit: "feature-month",
        billingUnitsPerFeatureUnit: 1,
        unitCost: 3,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
      },
    ],
  });

  assert.equal(
    result.infrastructureBreakdown[0].originalFeatureQuantity,
    "1",
  );
  assert.equal(result.usageDrivenInfrastructureCost.toString(), "3");
});

test("04.04 duplicate feature/cost-driver versions are not double-counted", () => {
  const result = calculateCustomPlanPrice({
    ...common,
    features: [
      { featureId: "storage", limitValue: 1024, estimatedUsage: 1024 },
    ],
    infrastructureRates: [
      {
        id: "newest",
        featureId: "storage",
        costDriver: "storage",
        usageBasis: "limit_value",
        billingUnit: "GB-month",
        billingUnitsPerFeatureUnit: 0.0009765625,
        unitCost: 1,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
      },
      {
        id: "older-overlap",
        featureId: "storage",
        costDriver: "storage",
        usageBasis: "limit_value",
        billingUnit: "GB-month",
        billingUnitsPerFeatureUnit: 0.0009765625,
        unitCost: 100,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
      },
    ],
  });

  assert.equal(result.infrastructureBreakdown.length, 1);
  assert.equal(result.infrastructureBreakdown[0].rateId, "newest");
  assert.equal(result.usageDrivenInfrastructureCost.toString(), "1");
});

test("04.05 deprecated infrastructure rates are ignored", () => {
  const result = calculateCustomPlanPrice({
    ...common,
    features: [{ featureId: "x", estimatedUsage: 100 }],
    infrastructureRates: [
      {
        id: "deprecated",
        featureId: "x",
        costDriver: "old",
        usageBasis: "estimated_usage",
        billingUnit: "unit",
        billingUnitsPerFeatureUnit: 1,
        unitCost: 100,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "deprecated",
      },
    ],
  });

  assert.equal(result.usageDrivenInfrastructureCost.toString(), "0");
});

test("04.06 limit_value rate rejects a feature without a configured limit", () => {
  assert.throws(
    () =>
      calculateCustomPlanPrice({
        ...common,
        features: [{ featureId: "x", estimatedUsage: 1 }],
        infrastructureRates: [
          {
            id: "limit-rate",
            featureId: "x",
            costDriver: "capacity",
            usageBasis: "limit_value",
            billingUnit: "unit",
            billingUnitsPerFeatureUnit: 1,
            unitCost: 1,
            currency: "USD",
            operationalMultiplier: 1,
            variabilityReserve: 1,
            verificationStatus: "confirmed",
          },
        ],
      }),
    /requires a configured feature limit/,
  );
});

test("04.07 infrastructure rates use the quote-time FX snapshot", () => {
  const result = calculateCustomPlanPrice({
    ...common,
    quoteCurrency: "JOD",
    features: [{ featureId: "x", estimatedUsage: 10 }],
    infrastructureRates: [
      {
        id: "usd-infra",
        featureId: "x",
        costDriver: "compute",
        usageBasis: "estimated_usage",
        billingUnit: "unit",
        billingUnitsPerFeatureUnit: 1,
        unitCost: 1,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
      },
    ],
    fxRate: 0.71,
    fxSourceCurrency: "USD",
    fxTargetCurrency: "JOD",
  });

  assert.equal(result.usageDrivenInfrastructureCost.toString(), "7.1");
});

test("04.08 invalid conversion factor/multiplier is rejected", () => {
  assert.throws(
    () =>
      calculateCustomPlanPrice({
        ...common,
        features: [{ featureId: "x", estimatedUsage: 1 }],
        infrastructureRates: [
          {
            id: "bad",
            featureId: "x",
            costDriver: "compute",
            usageBasis: "estimated_usage",
            billingUnit: "unit",
            billingUnitsPerFeatureUnit: 0,
            unitCost: 1,
            currency: "USD",
            operationalMultiplier: 1,
            variabilityReserve: 1,
            verificationStatus: "confirmed",
          },
        ],
      }),
    /Invalid multiplier or conversion factor/,
  );
});
