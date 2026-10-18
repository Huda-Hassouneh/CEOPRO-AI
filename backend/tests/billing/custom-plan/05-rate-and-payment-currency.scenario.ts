import test from "node:test";
import assert from "node:assert/strict";
import { calculateCustomPlanPrice } from "../../../src/modules/subscription/service/custom-plan-pricing.service.js";
import {
  CUSTOM_PLAN_PAYMENT_CURRENCY,
  convertCustomPlanAmountToPaymentCurrency,
} from "../../../src/modules/subscription/service/custom-plan-payment-currency.service.js";

test("05.01 vendor rate converts through explicit USD -> JOD quote FX", () => {
  const result = calculateCustomPlanPrice({
    quoteCurrency: "JOD",
    features: [{ featureId: "api", estimatedUsage: 10 }],
    vendorRates: [
      {
        id: "usd-rate",
        featureId: "api",
        vendor: "provider",
        service: "api",
        billingUnit: "call",
        unitCost: 1,
        currency: "USD",
        operationalMultiplier: 1,
        variabilityReserve: 1,
        verificationStatus: "confirmed",
      },
    ],
    monthlyInfrastructureCost: 0,
    activePayingTenants: 1,
    estimatedOtherCost: 0,
    targetGrossMargin: 0,
    fxRate: 0.71,
    fxSourceCurrency: "USD",
    fxTargetCurrency: "JOD",
  });

  assert.equal(result.estimatedVendorCost.toString(), "7.1");
});

test("05.02 cross-currency rate without matching FX snapshot is rejected", () => {
  assert.throws(
    () =>
      calculateCustomPlanPrice({
        quoteCurrency: "JOD",
        features: [{ featureId: "api", estimatedUsage: 1 }],
        vendorRates: [
          {
            id: "usd-rate",
            featureId: "api",
            vendor: "provider",
            service: "api",
            billingUnit: "call",
            unitCost: 1,
            currency: "USD",
            operationalMultiplier: 1,
            variabilityReserve: 1,
            verificationStatus: "confirmed",
          },
        ],
        monthlyInfrastructureCost: 0,
        activePayingTenants: 1,
        estimatedOtherCost: 0,
        targetGrossMargin: 0,
      }),
    /Missing FX rate/,
  );
});

test("05.03 Stripe custom-plan payment currency remains USD", () => {
  assert.equal(CUSTOM_PLAN_PAYMENT_CURRENCY, "USD");
});

test("05.04 USD commercial amount does not require conversion", () => {
  assert.equal(
    convertCustomPlanAmountToPaymentCurrency({
      amount: 19.999,
      quoteCurrency: "USD",
      fxRate: null,
      fxSourceCurrency: null,
      fxTargetCurrency: null,
    }),
    20,
  );
});

test("05.05 JOD -> USD divides when stored pair is USD -> JOD", () => {
  assert.equal(
    convertCustomPlanAmountToPaymentCurrency({
      amount: 100,
      quoteCurrency: "JOD",
      fxRate: 0.709,
      fxSourceCurrency: "USD",
      fxTargetCurrency: "JOD",
    }),
    141.04,
  );
});

test("05.06 JOD -> USD multiplies when stored pair is JOD -> USD", () => {
  assert.equal(
    convertCustomPlanAmountToPaymentCurrency({
      amount: 100,
      quoteCurrency: "JOD",
      fxRate: 1.41,
      fxSourceCurrency: "JOD",
      fxTargetCurrency: "USD",
    }),
    141,
  );
});

test("05.07 payment conversion rejects missing or unusable FX", () => {
  assert.throws(
    () =>
      convertCustomPlanAmountToPaymentCurrency({
        amount: 100,
        quoteCurrency: "JOD",
        fxRate: null,
        fxSourceCurrency: "USD",
        fxTargetCurrency: "JOD",
      }),
    /Missing payment FX rate/,
  );

  assert.throws(
    () =>
      convertCustomPlanAmountToPaymentCurrency({
        amount: 100,
        quoteCurrency: "JOD",
        fxRate: 1,
        fxSourceCurrency: "EUR",
        fxTargetCurrency: "GBP",
      }),
    /does not support payment conversion/,
  );
});

test("05.08 payment conversion rejects negative amount and non-positive FX", () => {
  assert.throws(
    () =>
      convertCustomPlanAmountToPaymentCurrency({
        amount: -1,
        quoteCurrency: "JOD",
        fxRate: 0.709,
        fxSourceCurrency: "USD",
        fxTargetCurrency: "JOD",
      }),
    /Invalid custom-plan payment amount/,
  );

  assert.throws(
    () =>
      convertCustomPlanAmountToPaymentCurrency({
        amount: 100,
        quoteCurrency: "JOD",
        fxRate: 0,
        fxSourceCurrency: "USD",
        fxTargetCurrency: "JOD",
      }),
    /Payment FX rate must be greater than zero/,
  );
});
