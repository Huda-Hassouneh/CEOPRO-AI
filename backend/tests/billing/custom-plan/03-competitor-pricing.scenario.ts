import test from "node:test";
import assert from "node:assert/strict";
import { calculateCustomPlanPrice } from "../../../src/modules/subscription/service/custom-plan-pricing.service.js";

function input(overrides: Record<string, unknown> = {}) {
  return {
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
        id: "cu-rate",
        featureId: "competitor-management",
        feature: { code: "competitor_management" },
        vendor: "collector",
        service: "browser",
        billingUnit: "CU",
        unitCost: 0.2,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed" as const,
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
        vendor: "search",
        service: "credits",
        billingUnit: "credit",
        unitCost: 0.002,
        currency: "USD",
        operationalMultiplier: 2,
        variabilityReserve: 1,
        verificationStatus: "confirmed" as const,
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
    ...overrides,
  };
}

test("03.01 competitor price = competitor count × checks × rate-specific units", () => {
  const result = calculateCustomPlanPrice(input());

  assert.equal(result.estimatedVendorCost.toString(), "2.4");
  assert.deepEqual(
    result.vendorBreakdown.map((row) => [
      row.billingUnit,
      row.estimatedUsage,
      row.usageCalculation?.competitorCount,
      row.usageCalculation?.monitoringRunsPerMonth,
    ]),
    [
      ["CU", "6", "5", "4"],
      ["credit", "300", "5", "4"],
    ],
  );
});

test("03.02 each vendor rate keeps its own billing unit and usage assumption", () => {
  const result = calculateCustomPlanPrice(input());

  assert.equal(result.vendorBreakdown[0].billingUnit, "CU");
  assert.equal(
    result.vendorBreakdown[0].usageCalculation?.unitsPerCompetitorCheck,
    "0.3",
  );
  assert.equal(result.vendorBreakdown[1].billingUnit, "credit");
  assert.equal(
    result.vendorBreakdown[1].usageCalculation?.unitsPerCompetitorCheck,
    "15",
  );
});

test("03.03 explicit checks-per-month wins over derived 30-day cadence", () => {
  const changed = input();
  (changed.features[0] as any).configuration = {
    monitoringFrequencyMinutes: 1440,
    monitoringChecksPerMonth: 7,
  };

  const result = calculateCustomPlanPrice(changed as any);
  assert.equal(
    result.vendorBreakdown[0].usageCalculation?.monitoringRunsPerMonth,
    "7",
  );
});

test("03.04 configured monitoring requires positive tracked competitor capacity", () => {
  const changed = input();
  changed.features = [changed.features[0]];

  assert.throws(
    () => calculateCustomPlanPrice(changed as any),
    /tracked_competitors must be selected with a positive limit/,
  );
});

test("03.05 configured monitoring requires rate-specific usage assumption", () => {
  const changed = input();
  (changed.vendorRates[0] as any).metadata = undefined;

  assert.throws(
    () => calculateCustomPlanPrice(changed as any),
    /Missing competitor-monitoring usage assumption/,
  );
});

test("03.06 usage assumption must be positive", () => {
  const changed = input();
  (changed.vendorRates[0] as any).metadata = {
    usageAssumption: {
      model: "competitor_monitoring",
      unitsPerCompetitorCheck: 0,
    },
  };

  assert.throws(
    () => calculateCustomPlanPrice(changed as any),
    /Invalid competitor-monitoring usage assumption/,
  );
});

test("03.07 monitoring frequency must be a positive integer", () => {
  const changed = input();
  (changed.features[0] as any).configuration = {
    monitoringFrequencyMinutes: 0,
    monitoringChecksPerMonth: 4,
  };

  assert.throws(
    () => calculateCustomPlanPrice(changed as any),
    /Invalid competitor monitoring frequency/,
  );
});

test("03.08 checks per month must be positive", () => {
  const changed = input();
  (changed.features[0] as any).configuration = {
    monitoringFrequencyMinutes: 10080,
    monitoringChecksPerMonth: 0,
  };

  assert.throws(
    () => calculateCustomPlanPrice(changed as any),
    /Invalid competitor monitoring checks per month/,
  );
});

test("03.09 legacy quote without cadence keeps legacy estimated-usage behavior", () => {
  const changed = input();
  (changed.features[0] as any).configuration = null;

  const result = calculateCustomPlanPrice(changed as any);

  assert.equal(result.vendorBreakdown[0].estimatedUsage, "1");
  assert.equal(result.vendorBreakdown[0].usageCalculation, null);
});
