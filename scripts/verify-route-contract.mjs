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

  ["src/modules/subscription/index.ts", 'router.post(\n  "/",\n  authenticateUser,\n  requireTenant,\n  requirePermission("all"),\n  onBoardingHandler\n)'],
  ["src/modules/subscription/index.ts", 'router.use("/plans", plansRoutes)'],
  ["src/modules/subscription/index.ts", 'router.use("/promo-codes", promoCodeRoutes)'],
  ["src/modules/subscription/index.ts", 'router.use("/custom-plans", customPlanRoutes)'],

  ["src/modules/subscription/route/custom-plan.routes.ts", 'router.get("/", listCustomPlansHandler)'],
  ["src/modules/platform-admin/platform-admin.routes.ts", 'router.get("/billing/custom-quotes", read, listPlatformQuotesHandler)'],
  ["src/modules/subscription/route/custom-plan.routes.ts", '"/quotes/:id/calculate"'],
  ["src/modules/subscription/route/custom-plan.routes.ts", '"/quotes/:id/approve"'],
  ["src/modules/subscription/route/custom-plan.routes.ts", '"/quotes/:id/accept"'],
  ["src/modules/subscription/route/custom-plan.routes.ts", '"/vendor-rates"'],

  ["src/modules/subscription/route/plans.routes.ts", 'router.get("/", getPlansHandler)'],
  ["src/modules/subscription/route/plans.routes.ts", 'router.post(\n  "/",'],
  ["src/modules/subscription/route/plans.routes.ts", 'router.patch(\n  "/:id",'],

  ["src/modules/subscription/route/promo-codes.routes.ts", 'router.get("/", requirePlatformRole, requirePlatformPermission("billing.read"), getPromocodeHandler)'],
  ["src/modules/subscription/route/promo-codes.routes.ts", 'router.post(\n  "/",'],
  ["src/modules/subscription/route/promo-codes.routes.ts", 'router.post(\n  "/validate",'],
  ["src/modules/subscription/route/promo-codes.routes.ts", 'router.patch(\n  "/:id",'],
  ["src/modules/subscription/route/promo-codes.routes.ts", '"/:promoCodeId/plans/:planId"'],

  ["src/modules/subscription/route/subscriptions.routes.ts", 'router.get("/current", getCurrentSubscription)'],
  ["src/modules/subscription/route/subscriptions.routes.ts", '"/current/cancel"'],
  ["src/modules/subscription/route/subscriptions.routes.ts", '"/current/cancel/undo"'],
  ["src/modules/subscription/route/subscriptions.routes.ts", '"/current/plan"'],
  ["src/modules/subscription/route/subscriptions.routes.ts", '"/checkout"'],
  ["src/modules/subscription/route/invoice.routes.ts", 'router.get("/invoices"'],

  ["src/modules/features/index.ts", 'router.use("/features", featuresRoutes)'],
  ["src/modules/features/index.ts", 'router.use("/features", featureOperationRoutes)'],
  ["src/modules/features/index.ts", 'router.use("/", planFeaturesRoutes)'],
  ["src/modules/features/routes/features-managment.route.ts", 'router.get("/",'],
  ["src/modules/features/routes/features-managment.route.ts", '"/:id",'],
  ["src/modules/features/routes/features-managment.route.ts", 'router.post(\n  "/",'],
  ["src/modules/features/routes/features-managment.route.ts", 'router.patch(\n  "/:id",'],
  ["src/modules/features/routes/feature-plan.ts", '"/plans/:plan_id/features"'],
  ["src/modules/features/routes/feature-plan.ts", '"/plans/:plan_id/features/:feature_id"'],
  ["src/modules/features/routes/feature-plan.ts", '"/subscriptions/current/usage"'],

  ["src/modules/platform-admin/platform-admin.routes.ts", 'router.get("/me", platformMeHandler)'],
  ["src/modules/platform-admin/platform-admin.routes.ts", '"/billing/custom-plans/:id/status"'],
  ["src/modules/platform-admin/platform-admin.routes.ts", '"/billing/pricing-policy"'],
  ["src/modules/platform-admin/platform-admin.routes.ts", '"/billing/vendor-rates"'],

  ["src/modules/subscription/External Services/Payment providers/stripe/stripeRoutes.ts", 'router.post(\n  "/",']
];

const failures = [];
for (const [file, snippet] of checks) {
  if (!source(file).includes(snippet)) {
    failures.push(`${file}: ${JSON.stringify(snippet)}`);
  }
}

if (failures.length > 0) {
  console.error("Route contract verification failed:");
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log(`Route contract verification passed (${checks.length} checks).`);
