import test from "node:test";
import assert from "node:assert/strict";
import {
  approveCustomPlanQuoteSchema,
  customPlanInstantCheckoutSchema,
  customPlanManualReviewSchema,
  customPlanPreviewSchema,
  infrastructureRateSchema,
  updateInfrastructureRateSchema,
  updateVendorRateSchema,
  vendorRateSchema,
} from "../../../src/modules/subscription/types/custom-plan.dto.js";
import { UUID_A } from "./_helpers.js";

test("01.01 preview accepts a valid limit feature selection", () => {
  const parsed = customPlanPreviewSchema.parse({
    billingPeriod: "monthly",
    features: [{ featureId: UUID_A, limitValue: 100 }],
  });

  assert.equal(parsed.billingPeriod, "monthly");
  assert.equal(parsed.features[0].limitValue, 100);
});

test("01.02 preview defaults billing period to monthly", () => {
  const parsed = customPlanPreviewSchema.parse({
    features: [{ featureId: UUID_A, limitValue: 1 }],
  });

  assert.equal(parsed.billingPeriod, "monthly");
});

test("01.03 preview rejects malformed feature ids", () => {
  assert.throws(() =>
    customPlanPreviewSchema.parse({
      features: [{ featureId: "not-a-uuid", limitValue: 1 }],
    }),
  );
});

test("01.04 preview rejects unknown browser-supplied pricing fields", () => {
  assert.throws(() =>
    customPlanPreviewSchema.parse({
      features: [{ featureId: UUID_A, limitValue: 1 }],
      billingPeriod: "monthly",
      price: 0.01,
      currency: "USD",
    }),
  );
});

test("01.05 monitoring configuration requires a positive integer frequency", () => {
  assert.throws(() =>
    customPlanPreviewSchema.parse({
      features: [
        {
          featureId: UUID_A,
          configuration: { monitoringFrequencyMinutes: 0 },
        },
      ],
    }),
  );

  assert.throws(() =>
    customPlanPreviewSchema.parse({
      features: [
        {
          featureId: UUID_A,
          configuration: { monitoringFrequencyMinutes: 1.5 },
        },
      ],
    }),
  );
});

test("01.06 instant checkout defaults to Stripe and rejects unsupported method names", () => {
  const parsed = customPlanInstantCheckoutSchema.parse({
    requestId: UUID_A,
    billingPeriod: "monthly",
    features: [{ featureId: UUID_A, limitValue: 1 }],
  });

  assert.equal(parsed.paymentMethod, "stripe");

  assert.throws(() =>
    customPlanInstantCheckoutSchema.parse({
      requestId: UUID_A,
      features: [{ featureId: UUID_A, limitValue: 1 }],
      paymentMethod: "cash",
    }),
  );
});

test("01.07 manual review requires an idempotency request UUID", () => {
  assert.throws(() =>
    customPlanManualReviewSchema.parse({
      requestId: "same-request",
      features: [{ featureId: UUID_A, limitValue: 1 }],
    }),
  );
});

test("01.08 approval requires a positive price", () => {
  assert.throws(() =>
    approveCustomPlanQuoteSchema.parse({
      finalPrice: 0,
    }),
  );

  assert.equal(
    approveCustomPlanQuoteSchema.parse({ finalPrice: 10 }).finalPrice,
    10,
  );
});

test("01.09 vendor-rate create rejects reversed effective dates", () => {
  assert.throws(() =>
    vendorRateSchema.parse({
      featureId: UUID_A,
      vendor: "Vendor",
      service: "API",
      billingUnit: "call",
      unitCost: 1,
      currency: "USD",
      effectiveFrom: "2026-10-10T00:00:00.000Z",
      effectiveTo: "2026-10-09T00:00:00.000Z",
    }),
  );
});

test("01.10 vendor-rate update must contain at least one field", () => {
  assert.throws(() => updateVendorRateSchema.parse({}));
});

test("01.11 infrastructure rate validates unit conversion and date window", () => {
  const parsed = infrastructureRateSchema.parse({
    featureId: UUID_A,
    costDriver: "storage",
    usageBasis: "limit_value",
    billingUnit: "GB-month",
    billingUnitsPerFeatureUnit: 0.0009765625,
    unitCost: 0.02,
    currency: "USD",
    effectiveFrom: "2026-10-01T00:00:00.000Z",
    effectiveTo: "2026-11-01T00:00:00.000Z",
  });

  assert.equal(parsed.usageBasis, "limit_value");
  assert.equal(parsed.billingUnitsPerFeatureUnit, 0.0009765625);

  assert.throws(() =>
    infrastructureRateSchema.parse({
      featureId: UUID_A,
      costDriver: "storage",
      usageBasis: "limit_value",
      billingUnit: "GB-month",
      billingUnitsPerFeatureUnit: 0,
      unitCost: 0.02,
      currency: "USD",
    }),
  );
});

test("01.12 infrastructure-rate update must contain at least one field", () => {
  assert.throws(() => updateInfrastructureRateSchema.parse({}));
});
