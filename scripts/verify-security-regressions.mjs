import fs from "node:fs";

const read = (file) => fs.readFileSync(file, "utf8");
const readAllMigrations = () => {
  const migrationsDir = "prisma/migrations";

  if (!fs.existsSync(migrationsDir)) {
    return "";
  }

  return fs
    .readdirSync(migrationsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => `${migrationsDir}/${entry.name}/migration.sql`)
    .filter((file) => fs.existsSync(file))
    .map((file) => read(file))
    .join("\n");
};

const allMigrations = readAllMigrations();
// -----------------------------------------------------------------------------
// Read frequently checked files once
// -----------------------------------------------------------------------------

const subscriptionService = read(
  "src/modules/subscription/service/subscription.service.ts"
);

const subscriptionIndex = read("src/modules/subscription/index.ts");

const stripeService = read(
  "src/modules/subscription/client/payment-providers/stripe/stripe.client.ts"
);

const webhookUtils = read("src/utils/webhook.ts");

const webhookRepo = read("src/modules/subscription/repo/webhook.repo.ts");

const promoRepo = read("src/modules/subscription/repo/promocodes.repo.ts");

const currencyUtils = read("src/utils/currency.ts");

const invoiceService = read(
  "src/modules/subscription/service/invoice.service.ts"
);

const validateFeatures = read("src/validators/validateFeatures.ts");

const usageRepo = read("src/modules/features/repo/usage.repo.ts");

const app = read("src/app.ts");
const env = read("src/config/env.ts");
const validateUser = read("src/validators/validateUser.ts");
const tokenUtils = read("src/utils/token.ts");

const plansRepo = read("src/modules/subscription/repo/plans.repo.ts");

const customPlanPricingService = read(
  "src/modules/subscription/service/custom-plan-pricing.service.ts"
);

const customPlanService = read(
  "src/modules/subscription/service/custom-plan.service.ts"
);

const customPlanRoutes = read(
  "src/modules/subscription/route/custom-plan.route.ts"
);

const plansService = read("src/modules/subscription/service/plans.service.ts");

const promoPlanService = read(
  "src/modules/subscription/service/promocodes-plans.service.ts"
);

// -----------------------------------------------------------------------------
// Platform administration / Admin Team
// -----------------------------------------------------------------------------

const platformRoutes = read(
  "src/modules/platform-admin/route/platform-admin.route.ts"
);

const validatePlatformUser = read("src/validators/validatePlatformUser.ts");

const userTenantRepo = read(
  "src/modules/subscription/repo/user-tenant.repo.ts"
);

const requestTypes = read("src/types/request.ts");

const ownerController = read(
  "src/modules/owner-portal/controller/owner.controller.ts"
);

const ownerWriteService = read(
  "src/modules/owner-portal/service/owner-write.service.ts"
);

const platformRoles = read("src/modules/owner-portal/types/platform-roles.ts");

// -----------------------------------------------------------------------------
// Checks
// -----------------------------------------------------------------------------

const checks = [
  {
    name: "checkout honors public payment_method contract",
    pass:
      subscriptionService.includes("data.payment_method") &&
      !subscriptionService.includes("data.payment_provider")
  },

  {
    name: "Stripe onboarding is authenticated and permission-gated",
    pass: subscriptionIndex.includes(
      'router.post(\n  "/",\n  authenticateUser,\n  requireTenant,\n  requirePermission("all"),\n  onBoardingHandler\n)'
    )
  },

  {
    name: "tenant-aware Stripe customer reuse does not fall back to userId",
    pass: stripeService.includes(
      "if (!existingCustomer && !tenantId && userId)"
    )
  },

  {
    name: "usage allocations are created from webhook synchronization",
    pass: webhookUtils.includes("ensureUsageAllocationsForSubscription")
  },

  {
    name: "payment transactions use an invoice idempotency key and upsert",
    pass:
      webhookRepo.includes("stripe:invoice:${invoice.id}") &&
      webhookRepo.includes("paymentTransaction.upsert")
  },

  {
    name: "promo redemption enforces tenant limits under serializable isolation",
    pass:
      promoRepo.includes("maxUsesPerUser") &&
      promoRepo.includes("TransactionIsolationLevel.Serializable")
  },

  {
    name: "currency conversion centralizes Stripe minor-unit rules",
    pass:
      currencyUtils.includes("ZERO_DECIMAL_CURRENCIES") &&
      invoiceService.includes("fromStripeMinorUnits")
  },

  {
    name: "entitlement statuses are centralized",
    pass:
      usageRepo.includes(
        'import { ACCESS_GRANTING_STATUSES } from "../../../constants/subscription.js"'
      ) &&
      usageRepo.includes("ACCESS_GRANTING_STATUSES") &&
      validateFeatures.includes("getFeatureAccessInfo")
  },

  {
    name: "runtime startup does not import the mock token generator",
    pass: !app.includes("mock-user") && !fs.existsSync("src/mock/mock-user.ts")
  },

  {
    name: "CORS allow-list is environment-driven",
    pass: app.includes("getCorsOrigins") && env.includes("CORS_ORIGINS")
  },

  {
    name: "global JSON error middleware is mounted",
    pass:
      app.includes("app.use(notFoundHandler)") &&
      app.includes("app.use(globalErrorHandler)")
  },

  {
    name: "JWT verification restricts accepted algorithms",
    pass:
      validateUser.includes('algorithms: ["HS256"]') &&
      tokenUtils.includes('algorithm: "HS256"')
  },

  {
    name: "subscription tenant foreign key and payment idempotency migration exist",
    pass:
      allMigrations.includes("subscriptions_tenant_id_fkey") &&
      allMigrations.includes("idempotency_key")
  },
  {
    name: "custom plans are tenant-private at checkout",
    pass: subscriptionService.includes(
      'validPlan.planType === "custom" && validPlan.tenantId !== userPayload.tenant_id'
    )
  },

  {
    name: "public plan listing excludes tenant-private custom plans",
    pass:
      plansRepo.includes('planType: "standard"') &&
      plansRepo.includes("tenantId: null")
  },

  {
    name: "custom pricing remains server authoritative",
    pass:
      customPlanPricingService.includes("minimumSafePrice") &&
      customPlanService.includes("finalPrice.lessThan") &&
      customPlanRoutes.includes('requirePermission("manage_catalog")')
  },

  {
    name: "accepted custom plans are immutable through generic catalog edits",
    pass: plansService.includes("Accepted custom plans are immutable")
  },

  {
    name: "tenant promo linking retains custom-plan ownership protection",
    pass:
      promoPlanService.includes('plan.planType === "custom"') &&
      promoPlanService.includes("plan.tenantId !== tenantId") &&
      promoPlanService.includes(
        "linkPromoCodePlanInternal(planId, promoCodeId, tenantId, false)"
      )
  },

  // ---------------------------------------------------------------------------
  // PLATFORM ADMIN SECURITY
  // ---------------------------------------------------------------------------

  {
    name: "platform administration requires verified platform membership",
    pass:
      platformRoutes.includes("requirePlatformRole") &&
      validatePlatformUser.includes("getActiveTenantUser") &&
      userTenantRepo.includes("businessType") &&
      validatePlatformUser.includes("businessType") &&
      validatePlatformUser.includes('"platform"')
  },

  {
    name: "platform administration is no longer hardcoded to owner role",
    pass:
      !validatePlatformUser.includes('PLATFORM_OWNER_ROLE_KEY = "owner"') &&
      !validatePlatformUser.includes("PLATFORM_OWNER_ROLE_KEY")
  },

  {
    name: "platform permissions come from SystemRole permissions",
    pass:
      userTenantRepo.includes("role: true") &&
      validatePlatformUser.includes("permissions") &&
      validatePlatformUser.includes("permissions?.all === true") &&
      validatePlatformUser.includes("permissions?.[permission] === true")
  },

  {
    name: "platform tenant information is attached to authenticated membership",
    pass:
      userTenantRepo.includes("tenant:") &&
      userTenantRepo.includes("businessType") &&
      requestTypes.includes("businessType")
  },

  // ---------------------------------------------------------------------------
  // ADMIN TEAM ROLE SECURITY
  // ---------------------------------------------------------------------------

  {
    name: "Admin Team supports non-owner platform roles",
    pass:
      platformRoles.includes('"admin"') &&
      platformRoles.includes('"manager"') &&
      platformRoles.includes('"accountant"') &&
      platformRoles.includes('"staff"')
  },

  {
    name: "owner cannot be assigned through Admin Team",
    pass:
      platformRoles.includes("INVITABLE_PLATFORM_ROLES") &&
      !platformRoles
        .split("INVITABLE_PLATFORM_ROLES")[1]
        ?.split("]")[0]
        ?.includes('"owner"')
  },

  {
    name: "Admin Team controller validates against assignable platform roles",
    pass: ownerController.includes("INVITABLE_PLATFORM_ROLES")
  },

  {
    name: "Admin Team cannot modify the platform owner",
    pass:
      ownerWriteService.includes('member.roleKey === "owner"') &&
      ownerWriteService.includes('throw new PortalError("forbidden")')
  },

  {
    name: "platform invitations cannot accept an owner role",
    pass: ownerWriteService.includes("isInvitablePlatformRole")
  },

  {
    name: "request model does not trust a browser-provided platform_role",
    pass: !requestTypes.includes("platform_role")
  },

  {
    name: "plan totals preserve fractional precision",
    pass: !plansService.includes("Math.round(calculateDiscountedPrice")
  }
];

// -----------------------------------------------------------------------------
// Output
// -----------------------------------------------------------------------------

const failed = checks.filter((check) => !check.pass);

for (const check of checks) {
  const marker = check.pass ? "PASS" : "FAIL";
  console.log(`${marker}: ${check.name}`);
}

if (failed.length > 0) {
  console.error(
    `\nSecurity regression verification failed (${failed.length}/${checks.length}).`
  );

  process.exitCode = 1;
} else {
  console.log(
    `\nSecurity regression verification passed (${checks.length} checks).`
  );
}
