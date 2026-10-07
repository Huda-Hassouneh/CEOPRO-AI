import fs from "node:fs";

const files = new Map();
const source = (file) => {
  if (!files.has(file)) files.set(file, fs.readFileSync(file, "utf8"));
  return files.get(file);
};

const checks = [
  ["src/app.ts", 'app.use("/stripe/webhooks", stripeRouter)'],
  ["src/app.ts", 'app.use("/platform-admin", platformAdminRouter)'],
  ["src/app.ts", 'app.use("/subscription", subscriptionModuleRouter)'],
  ["src/app.ts", 'app.use("/", featureModuleRouter)'],
  ["src/app.ts", 'app.get("/",'],

  ["src/modules/subscription/index.ts", 'router.use("/plans", plansRoutes)'],
  ["src/modules/subscription/index.ts", 'router.use("/promo-codes", promoCodeRoutes)'],
  ["src/modules/subscription/index.ts", 'router.use("/custom-plans", customPlanRoutes)'],

  ["src/modules/subscription/route/custom-plan.route.ts", 'router.get("/", listCustomPlansHandler)'],
  ["src/modules/platform-admin/route/platform-admin.route.ts", 'router.get("/billing/custom-quotes", read, listPlatformQuotesHandler)'],
  ["src/modules/subscription/route/custom-plan.route.ts", '"/quotes/:id/calculate"'],
  ["src/modules/subscription/route/custom-plan.route.ts", '"/quotes/:id/approve"'],
  ["src/modules/subscription/route/custom-plan.route.ts", '"/quotes/:id/accept"'],
  ["src/modules/subscription/route/custom-plan.route.ts", '"/vendor-rates"'],

  ["src/modules/subscription/route/plans.route.ts", 'router.get("/", getPlansHandler)'],
  ["src/modules/subscription/route/plans.route.ts", 'router.post(\n  "/",'],
  ["src/modules/subscription/route/plans.route.ts", 'router.patch(\n  "/:id",'],

  ["src/modules/subscription/route/promo-codes.route.ts", 'router.get("/", requirePlatformRole, requirePlatformPermission("billing.read"), getPromocodeHandler)'],
  ["src/modules/subscription/route/promo-codes.route.ts", 'router.post(\n  "/",'],
  ["src/modules/subscription/route/promo-codes.route.ts", 'router.post(\n  "/validate",'],
  ["src/modules/subscription/route/promo-codes.route.ts", 'router.patch(\n  "/:id",'],
  ["src/modules/subscription/route/promo-codes.route.ts", '"/:promoCodeId/plans/:planId"'],

  ["src/modules/subscription/route/subscriptions.route.ts", 'router.get("/current", getCurrentSubscription)'],
  ["src/modules/subscription/route/subscriptions.route.ts", '"/current/recovery"'],
  ["src/modules/subscription/route/subscriptions.route.ts", '"/current/cancel"'],
  ["src/modules/subscription/route/subscriptions.route.ts", '"/current/cancel/undo"'],
  ["src/modules/subscription/route/subscriptions.route.ts", '"/current/plan"'],
  ["src/modules/subscription/route/subscriptions.route.ts", '"/checkout"'],
  ["src/modules/subscription/route/invoice.route.ts", 'router.get("/invoices"'],

  ["src/modules/features/index.ts", 'router.use("/features", featuresRoutes)'],
  ["src/modules/features/index.ts", 'router.use("/features", featureOperationRoutes)'],
  ["src/modules/features/index.ts", 'router.use("/", planFeaturesRoutes)'],
  ["src/modules/features/route/features-management.route.ts", 'router.get("/",'],
  ["src/modules/features/route/features-management.route.ts", '"/:id",'],
  ["src/modules/features/route/features-management.route.ts", 'router.post(\n  "/",'],
  ["src/modules/features/route/features-management.route.ts", 'router.patch(\n  "/:id",'],
  ["src/modules/features/route/feature-plan.route.ts", '"/plans/:plan_id/features"'],
  ["src/modules/features/route/feature-plan.route.ts", '"/plans/:plan_id/features/:feature_id"'],
  ["src/modules/features/route/feature-plan.route.ts", '"/subscriptions/current/usage"'],

  ["src/modules/platform-admin/route/platform-admin.route.ts", 'router.get("/me", platformMeHandler)'],
  ["src/modules/platform-admin/route/platform-admin.route.ts", '"/billing/custom-plans/:id/status"'],
  ["src/modules/platform-admin/route/platform-admin.route.ts", '"/billing/pricing-policy"'],
  ["src/modules/platform-admin/route/platform-admin.route.ts", '"/billing/vendor-rates"'],

  ["src/modules/subscription/route/stripe-webhook.route.ts", 'router.post(\n  "/",']
];

const forbiddenChecks = [
  [
    "src/modules/subscription/index.ts",
    "onBoardingHandler",
    "shared Stripe Product initialization must not be exposed through runtime subscription routes",
  ],
];

const failures = [];
for (const [file, snippet] of checks) {
  if (!source(file).includes(snippet)) {
    failures.push(`${file}: missing ${JSON.stringify(snippet)}`);
  }
}

for (const [file, snippet, reason] of forbiddenChecks) {
  if (source(file).includes(snippet)) {
    failures.push(`${file}: forbidden ${JSON.stringify(snippet)} (${reason})`);
  }
}

if (failures.length > 0) {
  console.error("Route contract verification failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log(`Route contract verification passed (${checks.length} checks).`);
