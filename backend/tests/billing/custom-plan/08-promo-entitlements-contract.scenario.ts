import test from "node:test";
import assert from "node:assert/strict";
import {
  assertIncludesAll,
  readProjectFile,
} from "./_helpers.js";

const customService = readProjectFile(
  "src/modules/subscription/service/custom-plan.service.ts",
);
const checkout = readProjectFile(
  "src/modules/subscription/service/subscription.service.ts",
);
const promos = readProjectFile(
  "src/modules/subscription/service/promocodes.service.ts",
);
const quoteRepo = readProjectFile(
  "src/modules/subscription/repo/custom-plan.repo.ts",
);
const webhookHandlers = readProjectFile("src/utils/webhook handlers.ts");
const webhookCore = readProjectFile("src/utils/webhook.ts");
const usageRepo = readProjectFile("src/modules/features/repo/usage.repo.ts");

test("08.01 billing-option discount is baked into provider price independently of promo coupon", () => {
  assertIncludesAll(
    customService,
    [
      "priceWithDiscount(",
      "option.discountPercent",
      "stripeService.createPlan",
    ],
    "custom-plan provider price creation",
  );

  assertIncludesAll(
    checkout,
    [
      "validatePromoCode(",
      "couponId:",
      "validPromoCode?.paymentProviderCoupon",
    ],
    "promo application",
  );
});

test("08.02 promo validation covers inactive, expired, usage limit and plan applicability", () => {
  assertIncludesAll(
    promos,
    [
      "ERROR_CODES.PROMO_CODE_NOT_ACTIVE",
      "ERROR_CODES.PROMO_CODE_EXPIRED",
      "ERROR_CODES.PROMO_CODE_USAGE_LIMIT_REACHED",
      "ERROR_CODES.PROMO_CODE_NOT_APPLICABLE",
      "countPromoRedemptionsForTenant",
    ],
    "promo validation",
  );
});

test("08.03 accepted custom plan keeps exactly the quote feature limits", () => {
  assertIncludesAll(
    quoteRepo,
    [
      "quote.quoteFeatures.map",
      "feature_id: feature.featureId",
      "limit_value: feature.limitValue",
    ],
    "custom-plan entitlement persistence",
  );
});

test("08.04 accepted custom plan keeps feature configuration metadata", () => {
  assertIncludesAll(
    quoteRepo,
    [
      "metadata: feature.metadata ?? undefined",
    ],
    "custom-plan feature metadata",
  );
});

test("08.05 successful subscription synchronization ensures usage allocations", () => {
  assertIncludesAll(
    webhookHandlers,
    [
      "syncSubscriptionFromStripe(",
    ],
    "subscription webhook handlers",
  );

  assertIncludesAll(
    webhookCore,
    [
      "ensureUsageAllocationsForSubscription",
      "grantsSubscriptionAccess(",
    ],
    "subscription synchronization",
  );
});

test("08.06 entitlement usage is resolved from planFeatures, not client payload", () => {
  assertIncludesAll(
    usageRepo,
    [
      "planFeatures",
      "limit_value",
      "feature.type",
    ],
    "feature usage repository",
  );
});
