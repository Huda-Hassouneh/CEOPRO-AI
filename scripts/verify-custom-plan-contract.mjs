import fs from "node:fs";

const read = (file) => fs.readFileSync(file, "utf8");
const schema = read("prisma/schema.prisma");
const pricing = read("src/modules/subscription/service/custom-plan-pricing.service.ts");
const policy = read("src/modules/subscription/service/custom-plan-policy.service.ts");
const configurator = read("src/modules/subscription/service/custom-plan-configurator.service.ts");
const customService = read("src/modules/subscription/service/custom-plan.service.ts");
const customRepo = read("src/modules/subscription/repo/custom-plan.repo.ts");
const customRoutes = read("src/modules/subscription/route/custom-plan.routes.ts");
const platformRoutes = read("src/modules/platform-admin/platform-admin.routes.ts");
const plansRepo = read("src/modules/subscription/repo/plans.repo.ts");
const plansService = read("src/modules/subscription/service/plans.service.ts");
const transitionService = read("src/modules/subscription/service/plan-transition.service.ts");
const webhookHandlers = read("src/utils/webhook handlers.ts");
const checkout = read("src/modules/subscription/service/subscription.service.ts");
const promoPlan = read("src/modules/subscription/service/promocodes-plans.service.ts");
const stripe = read("src/modules/subscription/External Services/Payment providers/stripe/stripeService.ts");

const checks = [
  ["schema distinguishes standard and custom plans", schema.includes("enum PlanType") && schema.includes("planType") && schema.includes("tenantId")],
  ["quote and vendor-rate models exist", schema.includes("model CustomPlanQuote") && schema.includes("model CustomPlanQuoteFeature") && schema.includes("model VendorRate")],
  ["gross-margin floor uses estimated total cost", pricing.includes("estimatedTotalCost.div(ONE.sub(targetGrossMargin))")],
  ["vendor-cost-ratio floor is calculated separately", pricing.includes("estimatedVendorCost.div(maxVendorCostRevenueRatio)")],
  ["vendor-cost-ratio enforcement is policy-controlled rather than mandatory", pricing.includes("enforceVendorCostRatioFloor") && policy.includes("enforceVendorCostRatioFloor: false")],
  ["automated price adds fixed platform fee after safety floor", pricing.includes("minimumSafePrice.add(fixedPlatformFee)")],
  ["automated price can round up by policy", pricing.includes("roundUpToIncrement")],
  ["known multiplier and variability reserve are independent", pricing.includes("operationalMultiplier") && pricing.includes("variabilityReserve")],
  ["vendor-backed features cannot silently price without a vendor rate", pricing.includes("vendorCostRequiredFeatureIds") && pricing.includes("Missing vendor rate for feature(s)")],
  ["cross-currency vendor rates require an explicit FX snapshot", pricing.includes("Missing FX rate") && pricing.includes("fxSourceCurrency") && pricing.includes("fxTargetCurrency")],
  ["pricing policy is centralized in reusable AppConfig", policy.includes("CUSTOM_PLAN_PRICING_POLICY") || policy.includes("customPlanPricingPolicyKey")],
  ["customer configurator does not expose internal pricing policy", configurator.includes("getCustomPlanConfigurator") && !configurator.slice(configurator.indexOf("getCustomPlanConfigurator"), configurator.indexOf("previewCustomPlanConfiguration")).includes("targetGrossMargin")],
  ["checkout recalculates authoritative price", configurator.includes("Authoritative checkout-time recalculation") && configurator.includes("calculateConfiguration(previewInput)")],
  ["unsupported automatic configurations fall back to a persisted manual quote", configurator.includes("manualReviewRequired: true") && configurator.includes("createOrReuseAutomaticQuote")],
  ["automatic quote snapshots vendor rates and configuration hash", configurator.includes("configurationHash") && configurator.includes("pricingFingerprint") && configurator.includes("vendorRateIds") && configurator.includes("pricingSnapshot")],
  ["self-service endpoints exist", customRoutes.includes('"/configurator"') && customRoutes.includes('"/preview"') && customRoutes.includes('"/checkout"')],
  ["internal pricing policy endpoints require platform pricing permission", platformRoutes.includes('"/billing/pricing-policy"') && platformRoutes.includes('requirePlatformPermission("billing.pricing.manage")')],
  ["accepted quote final price becomes Plan.price", customRepo.includes("price: quote.finalPrice")],
  ["custom-plan conversion reuses PlanFeature", customRepo.includes("planFeature") && customRepo.includes("quoteFeatures")],
  ["Stripe consumes agreed final price, not pricing formulas", customService.includes("stripeService.createPlan") && customService.includes("finalPrice") && !stripe.includes("minimumSafePrice")],
  ["public plan list excludes tenant-private custom plans", plansRepo.includes('planType: "standard"') && plansRepo.includes("tenantId: null")],
  ["checkout enforces custom-plan tenant ownership", checkout.includes('validPlan.planType === "custom" && validPlan.tenantId !== userPayload.tenant_id')],
  ["generic plan editor cannot mutate accepted custom plans", plansService.includes('existingPlan.planType === "custom"') && plansService.includes("Accepted custom plans are immutable")],
  ["tenant promo linking enforces custom-plan tenant ownership", promoPlan.includes('plan.planType === "custom"') && promoPlan.includes("plan.tenantId !== tenantId") && promoPlan.includes("tenantId, false")],
  ["customer offer path is separated from internal quote pricing", customService.includes("getCustomPlanOffer") && customService.includes("finalPrice")],
  ["custom-plan transitions compare entitlements rather than price alone", transitionService.includes("analyzePlanTransition") && transitionService.includes('type = "mixed"') && plansService.includes("entitlementTransition")],
  ["any entitlement loss uses the period-end scheduling path", transitionService.includes('losses.length > 0 ? "period_end" : "immediate"') && plansService.includes('effectiveTiming === "period_end"')],
  ["custom-plan lifecycle is separated from subscription relationship", customService.includes("subscriptionRelationship") && customService.includes('planState: plan.isActive ? "enabled" : "disabled"')],
  ["schedule terminal webhook reconciles Stripe before clearing scheduled plan", webhookHandlers.includes("await syncSubscriptionFromStripe(stripeSubscription)") && webhookHandlers.includes("scheduledPlanId: null")],
  ["vendor rates are persisted separately from Plan.price", customRepo.includes("vendorRate") && schema.includes("model VendorRate")]
];

let failed = 0;
for (const [name, pass] of checks) {
  console.log(`${pass ? "PASS" : "FAIL"}: ${name}`);
  if (!pass) failed++;
}

if (failed) {
  console.error(`Custom-plan contract verification failed (${failed}/${checks.length}).`);
  process.exit(1);
}
console.log(`Custom-plan contract verification passed (${checks.length} checks).`);
