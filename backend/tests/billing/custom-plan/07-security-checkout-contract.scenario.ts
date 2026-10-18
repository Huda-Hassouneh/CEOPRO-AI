import test from "node:test";
import assert from "node:assert/strict";
import {
  assertIncludesAll,
  readProjectFile,
} from "./_helpers.js";

const repo = readProjectFile(
  "src/modules/subscription/repo/custom-plan.repo.ts",
);
const checkout = readProjectFile(
  "src/modules/subscription/service/subscription.service.ts",
);
const plansRepo = readProjectFile(
  "src/modules/subscription/repo/plans.repo.ts",
);
const promoPlan = readProjectFile(
  "src/modules/subscription/service/promocodes-plans.service.ts",
);
const routes = readProjectFile(
  "src/modules/subscription/route/custom-plan.route.ts",
);

test("07.01 tenant quote reads are scoped by both quote id and tenant id", () => {
  assertIncludesAll(
    repo,
    [
      "findQuoteForTenant",
      "where: { id, tenantId }",
      "listQuotesForTenant",
      "where: { tenantId }",
    ],
    "custom-plan repository",
  );
});

test("07.02 checkout rejects another tenant's custom plan", () => {
  assertIncludesAll(
    checkout,
    [
      'validPlan.planType === "custom"',
      "validPlan.tenantId !== userPayload.tenant_id",
      "ERROR_CODES.PLAN_NOT_AVAILABLE",
    ],
    "subscription checkout",
  );
});

test("07.03 public plan catalog excludes tenant-private custom plans", () => {
  assertIncludesAll(
    plansRepo,
    [
      'planType: "standard"',
      "tenantId: null",
      "getActivePlansWithLimits",
    ],
    "public plans repository",
  );
});

test("07.04 tenant promo linking cannot attach a promo to another tenant's custom plan", () => {
  assertIncludesAll(
    promoPlan,
    [
      'plan.planType === "custom"',
      "plan.tenantId !== tenantId",
      "ERROR_CODES.PLAN_NOT_AVAILABLE",
    ],
    "promo-plan linking",
  );
});

test("07.05 custom-plan routes require authentication and tenant context globally", () => {
  assertIncludesAll(
    routes,
    [
      "router.use(authenticateUser, requireTenant)",
      'requirePermission("manage_billing")',
    ],
    "custom-plan routes",
  );
});

test("07.06 internal pricing/rates require verified Platform permissions", () => {
  assertIncludesAll(
    routes,
    [
      "requirePlatformRole",
      'requirePlatformPermission("billing.read")',
      'requirePlatformPermission("billing.pricing.manage")',
    ],
    "custom-plan internal routes",
  );
});

test("07.07 PayPal is rejected rather than silently routed through Stripe", () => {
  assertIncludesAll(
    checkout,
    [
      'data.payment_method === "paypal"',
      "ERROR_CODES.UNSUPPORTED_PAYMENT_PROVIDER",
    ],
    "checkout payment provider handling",
  );
});
