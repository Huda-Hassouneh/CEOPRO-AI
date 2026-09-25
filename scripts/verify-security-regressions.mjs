import fs from "node:fs";

const read = (file) => fs.readFileSync(file, "utf8");

const checks = [
  {
    name: "checkout honors public payment_method contract",
    pass: read("src/modules/subscription/service/subscription.service.ts").includes("data.payment_method") &&
      !read("src/modules/subscription/service/subscription.service.ts").includes("data.payment_provider")
  },
  {
    name: "Stripe onboarding is authenticated and permission-gated",
    pass: read("src/modules/subscription/index.ts").includes(
      'router.post(\n  "/",\n  authenticateUser,\n  requireTenant,\n  requirePermission("all"),\n  onBoardingHandler\n)'
    )
  },
  {
    name: "tenant-aware Stripe customer reuse does not fall back to userId",
    pass: read("src/modules/subscription/External Services/Payment providers/stripe/stripeService.ts").includes(
      "if (!existingCustomer && !tenantId && userId)"
    )
  },
  {
    name: "usage allocations are created from webhook synchronization",
    pass: read("src/utils/webhook.ts").includes("ensureUsageAllocationsForSubscription")
  },
  {
    name: "payment transactions use an invoice idempotency key and upsert",
    pass: read("src/modules/subscription/repo/webhook.repo.ts").includes("stripe:invoice:${invoice.id}") &&
      read("src/modules/subscription/repo/webhook.repo.ts").includes("paymentTransaction.upsert")
  },
  {
    name: "promo redemption enforces tenant limits under serializable isolation",
    pass: read("src/modules/subscription/repo/promocodes.repo.ts").includes("maxUsesPerUser") &&
      read("src/modules/subscription/repo/promocodes.repo.ts").includes("TransactionIsolationLevel.Serializable")
  },
  {
    name: "currency conversion centralizes Stripe minor-unit rules",
    pass: read("src/utils/currency.ts").includes("ZERO_DECIMAL_CURRENCIES") &&
      read("src/modules/subscription/service/invoice.service.ts").includes("fromStripeMinorUnits")
  },
  {
    name: "entitlement statuses are centralized",
    pass: read("src/validators/validateFeatures.ts").includes("ACCESS_GRANTING_STATUSES") &&
      read("src/modules/features/repo/usage.repo.ts").includes("ACCESS_GRANTING_STATUSES")
  },
  {
    name: "runtime startup does not import the mock token generator",
    pass: !read("src/app.ts").includes("mock-user") && !fs.existsSync("src/mock/mock-user.ts")
  },
  {
    name: "CORS allow-list is environment-driven",
    pass: read("src/app.ts").includes("getCorsOrigins") && read("src/config/env.ts").includes("CORS_ORIGINS")
  },
  {
    name: "global JSON error middleware is mounted",
    pass: read("src/app.ts").includes("app.use(notFoundHandler)") &&
      read("src/app.ts").includes("app.use(globalErrorHandler)")
  },
  {
    name: "JWT verification restricts accepted algorithms",
    pass: read("src/validators/validateUser.ts").includes('algorithms: ["HS256"]') &&
      read("src/utils/token.ts").includes('algorithm: "HS256"')
  },
  {
    name: "subscription tenant foreign key and payment idempotency migration exist",
    pass: read("prisma/migrations/20260921020000_security_hardening/migration.sql").includes("subscriptions_tenant_id_fkey") &&
      read("prisma/migrations/20260921020000_security_hardening/migration.sql").includes("idempotency_key")
  },
  {
    name: "custom plans are tenant-private at checkout",
    pass: read("src/modules/subscription/service/subscription.service.ts").includes(
      'validPlan.planType === "custom" && validPlan.tenantId !== userPayload.tenant_id'
    )
  },
  {
    name: "public plan listing excludes tenant-private custom plans",
    pass: read("src/modules/subscription/repo/plans.repo.ts").includes('planType: "standard"') &&
      read("src/modules/subscription/repo/plans.repo.ts").includes('tenantId: null')
  },
  {
    name: "custom pricing remains server authoritative",
    pass: read("src/modules/subscription/service/custom-plan-pricing.service.ts").includes("minimumSafePrice") &&
      read("src/modules/subscription/service/custom-plan.service.ts").includes("finalPrice.lessThan") &&
      read("src/modules/subscription/route/custom-plan.routes.ts").includes('requirePermission("manage_catalog")')
  },
  {
    name: "accepted custom plans are immutable through generic catalog edits",
    pass: read("src/modules/subscription/service/plans.service.ts").includes("Accepted custom plans are immutable")
  },
  {
    name: "tenant promo linking retains custom-plan ownership protection",
    pass: read("src/modules/subscription/service/promocodes-plans.service.ts").includes('plan.planType === "custom"') &&
      read("src/modules/subscription/service/promocodes-plans.service.ts").includes('plan.tenantId !== tenantId') &&
      read("src/modules/subscription/service/promocodes-plans.service.ts").includes('linkPromoCodePlanInternal(planId, promoCodeId, tenantId, false)')
  },
  {
    name: "platform billing uses authoritative TenantUser owner membership",
    pass: read("src/modules/platform-admin/platform-admin.routes.ts").includes("requirePlatformRole") &&
      read("src/validators/validatePlatformUser.ts").includes("getActiveTenantUser") &&
      read("src/validators/validatePlatformUser.ts").includes('PLATFORM_OWNER_ROLE_KEY = "owner"') &&
      !read("src/types/request.ts").includes("platform_role")
  },
  {
    name: "plan totals preserve fractional precision",
    pass: !read("src/modules/subscription/service/plans.service.ts").includes("Math.round(calculateDiscountedPrice")
  }
];

const failed = checks.filter((check) => !check.pass);
for (const check of checks) {
  const marker = check.pass ? "PASS" : "FAIL";
  console.log(`${marker}: ${check.name}`);
}

if (failed.length > 0) {
  process.exitCode = 1;
} else {
  console.log(`Security regression verification passed (${checks.length} checks).`);
}
