import httpClient from "../../../shared/lib/httpClient.js";
import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import { previewList, previewSubscription, previewUsage, testingFeatures, testingPlans, testingPlanFeatureLinks } from "./uiTestingBillingData.js";
import { getApiError as parseApiError, getApiErrorMessage } from "../../../shared/lib/apiErrors.js";

const endpoints = Object.freeze({
  plans: "/subscription/plans",
  subscriptions: "/subscription",
  currentSubscription: "/subscription/current",
  recovery: "/subscription/current/recovery",
  checkout: "/subscription/checkout",
  currentPlan: "/subscription/current/plan",
  cancel: "/subscription/current/cancel",
  undoCancel: "/subscription/current/cancel/undo",
  usage: "/subscriptions/current/usage",
  invoices: "/subscription/invoices",
  promoCodes: "/subscription/promo-codes",
  features: "/features",
  customPlans: "/subscription/custom-plans",
  customPlanQuotes: "/subscription/custom-plans/quotes",
  customPlanConfigurator: "/subscription/custom-plans/configurator",
  customPlanPreview: "/subscription/custom-plans/preview",
  customPlanManualReview: "/subscription/custom-plans/manual-review",
  customPlanCheckout: "/subscription/custom-plans/checkout",
  customPlanPricingPolicy: "/subscription/custom-plans/pricing-policy",
  vendorRates: "/subscription/custom-plans/vendor-rates",
  scheduledPlanChange: "/subscription/current/plan/scheduled"
});

const unwrap = (request) => request.then((response) => response.data);
const unwrapData = (response) => response?.data ?? response;

export const getApiError = (error) => {
  const parsed = parseApiError(error);
  return {
    ...parsed,
    message: getApiErrorMessage(error),
    payload: parsed.payload
  };
};

export const isForbiddenBillingError = (error) => {
  const apiError = getApiError(error);
  return apiError.status === 403 || apiError.code === "FORBIDDEN";
};

const normalizeUsage = (response) => {
  const data = unwrapData(response);
  if (!data?.plan) return null;

  const usage = {};
  const limits = {};
  const features = {};

  for (const entitlement of data.entitlements ?? []) {
    const key = entitlement.feature_code;
    if (!key) continue;

    usage[key] = Number(entitlement.current_usage ?? 0);
    limits[key] = entitlement.limit ?? null;
    features[key] = {
      name: entitlement.name ?? key,
      name_ar: entitlement.name_ar,
      description: entitlement.description,
      description_ar: entitlement.description_ar,
      unit: entitlement.unit,
      unit_ar: entitlement.unit_ar,
      type: entitlement.type,
      aggregation_type: entitlement.aggregation_type,
      reset_cycle: entitlement.reset_cycle
    };
  }

  return {
    planId: data.plan.id,
    planName: data.plan.name,
    status: data.plan.status,
    periodStart: data.plan.period_start,
    renewsAt: data.plan.period_end,
    usage,
    limits,
    features,
    entitlements: data.entitlements ?? [],
    raw: data
  };
};

const unsupported = (capability) => {
  const error = new Error(`Backend capability is not available: ${capability}`);
  error.code = "BACKEND_CAPABILITY_UNAVAILABLE";
  return Promise.reject(error);
};

export const billingApi = Object.freeze({
  getPlans: () => UI_TESTING_MODE ? previewList(testingPlans) : unwrap(httpClient.get(endpoints.plans)),
  cancelScheduledPlanChange: () =>
    unwrap(httpClient.delete(endpoints.scheduledPlanChange)),
  createPlan: (payload) => unwrap(httpClient.post(endpoints.plans, payload)),
  updatePlan: (planId, payload) =>
    unwrap(
      httpClient.patch(
        `${endpoints.plans}/${encodeURIComponent(planId)}`,
        payload
      )
    ),

  getSubscription: () => UI_TESTING_MODE ? previewSubscription() : unwrap(httpClient.get(endpoints.currentSubscription)),
  createSubscriptionRecovery: () => unwrap(httpClient.post(endpoints.recovery)),
  getSubscriptionUsage: async () =>
    UI_TESTING_MODE ? previewUsage() : normalizeUsage(await unwrap(httpClient.get(endpoints.usage))),
  createCheckout: (payload) =>
    unwrap(httpClient.post(endpoints.checkout, payload)),
  changePlan: (payload) =>
    unwrap(httpClient.patch(endpoints.currentPlan, payload)),
  cancelSubscription: () => unwrap(httpClient.patch(endpoints.cancel)),
  resumeSubscription: () => unwrap(httpClient.patch(endpoints.undoCancel)),

  getInvoices: () => UI_TESTING_MODE ? previewList() : unwrap(httpClient.get(endpoints.invoices)),

  validateCoupon: (payload) =>
    unwrap(httpClient.post(`${endpoints.promoCodes}/validate`, payload)),
  getPromoCodes: () => UI_TESTING_MODE ? previewList() : unwrap(httpClient.get(endpoints.promoCodes)),
  createPromoCode: (payload) =>
    unwrap(httpClient.post(endpoints.promoCodes, payload)),
  updatePromoCode: (promoCodeId, payload) =>
    unwrap(
      httpClient.patch(
        `${endpoints.promoCodes}/${encodeURIComponent(promoCodeId)}`,
        payload
      )
    ),
  linkPromoCodeToPlan: ({ promoCodeId, planId }) =>
    unwrap(
      httpClient.post(
        `${endpoints.promoCodes}/${encodeURIComponent(promoCodeId)}/plans/${encodeURIComponent(planId)}`
      )
    ),

  getFeatures: () => UI_TESTING_MODE ? previewList(testingFeatures) : unwrap(httpClient.get(endpoints.features)),
  getFeature: (featureId) =>
    unwrap(
      httpClient.get(`${endpoints.features}/${encodeURIComponent(featureId)}`)
    ),
  createFeature: (payload) =>
    unwrap(httpClient.post(endpoints.features, payload)),
  updateFeature: (featureId, payload) =>
    unwrap(
      httpClient.patch(
        `${endpoints.features}/${encodeURIComponent(featureId)}`,
        payload
      )
    ),
  getPlanFeatures: (planId) =>
    UI_TESTING_MODE ? previewList(testingPlanFeatureLinks(planId)) : unwrap(httpClient.get(`/plans/${encodeURIComponent(planId)}/features`)),
  linkFeatureToPlan: (planId, payload) =>
    unwrap(
      httpClient.post(`/plans/${encodeURIComponent(planId)}/features`, payload)
    ),
  unlinkFeatureFromPlan: ({ planId, featureId }) =>
    unwrap(
      httpClient.delete(
        `/plans/${encodeURIComponent(planId)}/features/${encodeURIComponent(featureId)}`
      )
    ),
  updatePlanFeatureLimit: ({ planId, featureId, limitValue }) =>
    unwrap(
      httpClient.patch(
        `/plans/${encodeURIComponent(planId)}/features/${encodeURIComponent(featureId)}`,
        { limit_value: limitValue }
      )
    ),

  getCustomPlans: () => UI_TESTING_MODE ? previewList() : unwrap(httpClient.get(endpoints.customPlans)),
  getCustomPlanConfigurator: () =>
    UI_TESTING_MODE ? Promise.resolve({
      data: { features: testingFeatures.map(feature => ({ ...feature, type: "boolean" })), billingOptions: testingPlans[0].pricingOptions, preview: true },
      preview: true,
    }) : unwrap(httpClient.get(endpoints.customPlanConfigurator)),
  previewCustomPlan: (payload) =>
    unwrap(httpClient.post(endpoints.customPlanPreview, payload)),
  requestCustomPlanManualReview: (payload) =>
    unwrap(httpClient.post(endpoints.customPlanManualReview, payload)),
  checkoutCustomPlan: (payload) =>
    unwrap(httpClient.post(endpoints.customPlanCheckout, payload)),
  getCustomPlanPricingPolicy: () =>
    UI_TESTING_MODE ? Promise.resolve({ data: { currency: "USD", featureLimits: {}, monitoringCadences: [] }, preview: true }) : unwrap(httpClient.get(endpoints.customPlanPricingPolicy)),
  updateCustomPlanPricingPolicy: (payload) =>
    unwrap(httpClient.patch(endpoints.customPlanPricingPolicy, payload)),
  getCustomPlanQuotes: () => UI_TESTING_MODE ? previewList() : unwrap(httpClient.get(endpoints.customPlanQuotes)),
  getCustomPlanQuote: (quoteId) =>
    unwrap(
      httpClient.get(
        `${endpoints.customPlanQuotes}/${encodeURIComponent(quoteId)}`
      )
    ),
  getCustomPlanOffer: (quoteId) =>
    unwrap(
      httpClient.get(
        `${endpoints.customPlanQuotes}/${encodeURIComponent(quoteId)}/offer`
      )
    ),
  createCustomPlanQuote: (payload) =>
    unwrap(httpClient.post(endpoints.customPlanQuotes, payload)),
  updateCustomPlanQuote: (quoteId, payload) =>
    unwrap(
      httpClient.patch(
        `${endpoints.customPlanQuotes}/${encodeURIComponent(quoteId)}`,
        payload
      )
    ),
  calculateCustomPlanQuote: (quoteId) =>
    unwrap(
      httpClient.post(
        `${endpoints.customPlanQuotes}/${encodeURIComponent(quoteId)}/calculate`
      )
    ),
  approveCustomPlanQuote: (quoteId, payload) =>
    unwrap(
      httpClient.post(
        `${endpoints.customPlanQuotes}/${encodeURIComponent(quoteId)}/approve`,
        payload
      )
    ),
  sendCustomPlanQuote: (quoteId) =>
    unwrap(
      httpClient.post(
        `${endpoints.customPlanQuotes}/${encodeURIComponent(quoteId)}/send`
      )
    ),
  rejectCustomPlanQuote: (quoteId) =>
    unwrap(
      httpClient.post(
        `${endpoints.customPlanQuotes}/${encodeURIComponent(quoteId)}/reject`
      )
    ),
  acceptCustomPlanQuote: (quoteId) =>
    unwrap(
      httpClient.post(
        `${endpoints.customPlanQuotes}/${encodeURIComponent(quoteId)}/accept`
      )
    ),
  getVendorRates: () => UI_TESTING_MODE ? previewList() : unwrap(httpClient.get(endpoints.vendorRates)),
  createVendorRate: (payload) =>
    unwrap(httpClient.post(endpoints.vendorRates, payload)),
  updateVendorRate: (rateId, payload) =>
    unwrap(
      httpClient.patch(
        `${endpoints.vendorRates}/${encodeURIComponent(rateId)}`,
        payload
      )
    ),

  // No matching backend contracts exist for these legacy preview flows.
  calculateTax: () => unsupported("tax calculation"),
  paymentWebhookStatus: () => unsupported("payment webhook status polling"),
  createUpgradeCheckout: () => unsupported("separate upgrade checkout")
});
