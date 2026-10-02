import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = process.cwd();
const read = (path) => readFileSync(resolve(root, path), "utf8");
const api = read("src/features/billing/api/billingApi.js");
const platformApi = read(
  "src/features/platform-admin/api/platformBillingApi.js"
);
const router = read("src/app/router/index.jsx");
const adminRoutes = read("src/features/platform-admin/routes.jsx");
const routePaths = read("src/app/router/routePaths.js");
const tenantBilling = read(
  "src/features/billing/pages/PlansSubscriptionPage.jsx"
);
const billingSources = [
  "src/features/billing/api/billingApi.js",
  "src/features/billing/pages/PlansSubscriptionPage.jsx",
  "src/features/billing/pages/ChoosePlanPage.jsx",
  "src/features/billing/pages/BillingCheckoutPage.jsx",
  "src/features/billing/pages/BillingCustomPlanPage.jsx",
  "src/features/billing/pages/BillingCatalogPage.jsx",
  "src/features/billing/pages/CustomPlanOfferPage.jsx",
  "src/features/billing/components/CustomPlanQuoteManager.jsx",
  "src/features/billing/pages/CheckoutPage.jsx",
  "src/features/billing/pages/PaymentSuccessPage.jsx",
  "src/features/billing/pages/PaymentFailedPage.jsx",
  "src/features/billing/hooks/useSubscriptionRecovery.js",
  "src/features/billing/components/SubscriptionRecoveryBanner.jsx",
  "src/features/billing/utils/subscriptionStatus.js",
  "src/features/billing/utils/planChangeResult.js",
  "src/features/onboarding/pages/OnboardingSubscriptionSuccessPage.jsx",
  "src/features/onboarding/pages/OnboardingPlanSelectionPage.jsx",
  "src/features/onboarding/pages/OnboardingPaymentPage.jsx",
  "src/features/onboarding/pages/OnboardingCustomPlanPage.jsx"
]
  .map(read)
  .join("\n");

const requiredApiContracts = [
  "/subscription/plans",
  "/subscription/current",
  "/subscription/current/recovery",
  "/subscription/checkout",
  "/subscription/current/plan",
  "/subscription/current/cancel",
  "/subscription/current/cancel/undo",
  "/subscriptions/current/usage",
  "/subscription/invoices",
  "/subscription/promo-codes",
  "/subscription/custom-plans",
  "/subscription/custom-plans/configurator",
  "/subscription/custom-plans/preview",
  "/subscription/custom-plans/checkout"
];

const requiredPlatformContracts = [
  "/platform-admin/billing",
  "/plans",
  "/custom-plans",
  "/custom-quotes",
  "/pricing-policy",
  "/vendor-rates",
  "/promo-codes",
  "/features",
  "/subscriptions"
];

const obsoleteContracts = [
  "'/subscription/subscriptions/current'",
  '"/subscription/subscriptions/current"',
  "'/subscription/subscriptions/checkout'",
  '"/subscription/subscriptions/checkout"',
  "'/promo-codes/validate'",
  '"/promo-codes/validate"',
  "'/checkout/upgrade'",
  '"/checkout/upgrade"'
];

const failures = [];
for (const contract of requiredApiContracts) {
  if (!api.includes(contract))
    failures.push(`Missing tenant billing contract in billingApi: ${contract}`);
}
for (const contract of requiredPlatformContracts) {
  if (!platformApi.includes(contract))
    failures.push(`Missing platform billing contract: ${contract}`);
}
for (const contract of obsoleteContracts) {
  if (billingSources.includes(contract))
    failures.push(
      `Obsolete subscription contract is still referenced: ${contract}`
    );
}
if (billingSources.includes("localStorage.accessToken"))
  failures.push("Billing still reads localStorage.accessToken directly.");

if (!api.includes("createSubscriptionRecovery"))
  failures.push("Subscription recovery API helper is missing.");
if (!billingSources.includes("useSubscriptionRecovery"))
  failures.push("Subscription recovery is not wired into the frontend billing flow.");
if (!billingSources.includes("SubscriptionRecoveryBanner"))
  failures.push("Billing management does not expose a subscription recovery state.");
if (!routePaths.includes('billingCatalog: "/billing/catalog"'))
  failures.push("Legacy billing catalog redirect path is missing.");
if (!routePaths.includes('platformBilling: "/admin/billing"'))
  failures.push("Platform billing route path is missing.");
if (!routePaths.includes('customPlanOffer: "/billing/custom-offer/:quoteId"'))
  failures.push("Custom plan offer route path is missing.");
if (!router.includes("to={routePaths.platformBilling}"))
  failures.push(
    "Legacy billing catalog route does not redirect to platform billing."
  );
if (!/path:\s*["']billing["']/.test(adminRoutes)) {
  failures.push(
    "Platform billing page is not mounted in the platform-admin router."
  );
}
if (!router.includes("<CustomPlanOfferPage />"))
  failures.push("Custom plan offer page is not mounted.");
if (
  tenantBilling.includes("Manage Catalog") ||
  tenantBilling.includes("canManageCatalog") ||
  tenantBilling.includes("getCustomPlanPricingPolicy")
)
  failures.push("Tenant billing still exposes platform catalog management.");
if (
  billingSources.includes(
    "Backend capability is not available: custom plan quote"
  )
)
  failures.push(
    "Custom plan quote still uses the legacy unsupported API path."
  );

const billingCheckout = read(
  "src/features/billing/pages/BillingCheckoutPage.jsx"
);
const planChangeResult = read(
  "src/features/billing/utils/planChangeResult.js"
);
if (!billingCheckout.includes("response?.data ?? null"))
  failures.push("Billing checkout does not inspect the authoritative plan-change result payload.");
if (!billingCheckout.includes("isKnownPlanChangeState"))
  failures.push("Billing checkout does not validate explicit plan-change states.");
if (
  !planChangeResult.includes('"payment_action_required"') ||
  !planChangeResult.includes('"payment_pending"') ||
  !planChangeResult.includes('"scheduled"') ||
  !planChangeResult.includes('"failed"')
)
  failures.push("Plan-change result policy is missing required payment/scheduling states.");
if (billingCheckout.includes('response?.message || t("billing.checkoutInApp.changeSuccess")'))
  failures.push("Billing checkout still treats every successful HTTP plan-change response as an applied change.");

const customPage = read(
  "src/features/onboarding/pages/OnboardingCustomPlanPage.jsx"
);
const planSelector = read("src/features/billing/components/PlanSelector.jsx");
const paymentPage = read(
  "src/features/onboarding/pages/OnboardingPaymentPage.jsx"
);
if (customPage.includes("Custom plans are not available"))
  failures.push("Onboarding still disables the custom-plan flow.");
if (!customPage.includes("previewCustomPlan"))
  failures.push("Custom builder is not connected to server-side live pricing.");
if (
  !planSelector.includes("showCustomPlan") ||
  !planSelector.includes("Build Your Plan")
)
  failures.push("Plan selector does not render the custom-plan option.");
if (!paymentPage.includes("checkoutCustomPlan"))
  failures.push(
    "Onboarding payment does not support authoritative custom-plan checkout."
  );

if (failures.length) {
  console.error(
    `Subscription integration verification failed (${failures.length}):`
  );
  for (const failure of failures) console.error(`- ${failure}`);
  process.exit(1);
}

console.log(
  `Subscription integration verification passed (${requiredApiContracts.length} tenant + ${requiredPlatformContracts.length} platform route contracts checked).`
);
