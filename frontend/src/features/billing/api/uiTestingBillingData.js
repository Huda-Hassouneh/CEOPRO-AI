import { PREVIEW_PLANS, getPreviewPlanPrice } from "../../../shared/catalog/planCatalog.js";

/** Only used in development UI preview. Deliberately fictional, not Stripe prices. */
const sampleFeatureCodes = [
  "dashboard_analytics", "data_integration", "market_intelligence", "demand_prediction",
  "rag_assistant", "document_extraction", "document_storage_mb", "competitor_management",
  "tracked_competitors", "report_generation", "inventory_intelligence", "marketing_image_generation"
];

export const testingFeatures = sampleFeatureCodes.map((code, index) => ({
  id: `preview-${index + 1}`,
  code,
  feature_code: code,
  name: code.replaceAll("_", " "),
  type: "boolean",
  isActive: true,
  preview: true,
}));

export const testingPlans = ["starter", "growth", "enterprise"].map((id, index) => {
  const original = PREVIEW_PLANS[id];
  return {
    id: `ui-preview-${id}`,
    name: id[0].toUpperCase() + id.slice(1),
    name_ar: original.name.ar,
    description: original.description.en,
    description_ar: original.description.ar,
    currency: "USD",
    basePrice: original.monthlyPrice,
    tier_level: index + 1,
    trialPeriodValue: original.trialDays,
    isActive: true,
    isPreview: true,
    features: Object.fromEntries(sampleFeatureCodes.map(code => [code, {
      type: "boolean", name: code.replaceAll("_", " "),
    }])),
    pricingOptions: ["monthly", "three-months", "six-months"].map(period => {
      const cost = getPreviewPlanPrice(id, period);
      return {
        period,
        months: cost.months,
        intervalUnit: "month",
        intervalCount: cost.months,
        discountPercent: cost.discountPercent,
        totalPrice: cost.total,
        monthlyEquivalent: cost.monthlyEquivalent,
        currency: "USD",
        stripePriceId: null,
        isPreview: true,
      };
    }),
  };
});

export const previewList = (data = []) => Promise.resolve({ data: structuredClone(data), preview: true });

export const previewNoSubscription = () =>
  Promise.reject(Object.assign(new Error("No subscription in UI preview"), {
    code: "SUBSCRIPTION_NOT_FOUND",
    response: { status: 404, data: { code: "SUBSCRIPTION_NOT_FOUND" } },
  }));


/** UI-only current subscription. No Stripe subscription or payment exists. */
export const previewSubscription = () => previewList({
  id: "preview-subscription-growth",
  planId: testingPlans[1].id,
  plan: testingPlans[1],
  status: "active",
  billingPeriod: "monthly",
  currency: "USD",
  currentPeriodStart: "2026-10-01T00:00:00Z",
  currentPeriodEnd: "2026-11-01T00:00:00Z",
  cancelAtPeriodEnd: false,
  preview: true,
});

export const previewUsage = () => {
  const definitions = [
    ["rag_assistant", 500000, 84200, "token"],
    ["document_extraction", 512000, 38400, "KB"],
    ["document_storage_mb", 10240, 2820, "MB"],
    ["tracked_competitors", 15, 6, "competitor"],
    ["connected_data_sources", 5, 3, "source"],
  ];
  const usage = Object.fromEntries(definitions.map(([code,, current]) => [code,current]));
  const limits = Object.fromEntries(definitions.map(([code,limit]) => [code,limit]));
  const features = Object.fromEntries(definitions.map(([code,,,unit]) => [code, {name: code.replaceAll("_", " "), type: "limit", unit}]));
  const entitlements = definitions.map(([code,limit,current_usage,unit]) => ({feature_code: code, name: features[code].name, type: "limit", unit, limit, current_usage, remaining: limit-current_usage, is_unlimited: false, is_exceeded: false}));
  for (const code of ["dashboard_analytics", "market_intelligence", "demand_prediction"]) {
    entitlements.push({feature_code: code, name: code.replaceAll("_", " "), type: "boolean", limit: null, current_usage: 0, is_unlimited: true});
    features[code] = { name: code.replaceAll("_", " "), type: "boolean" };
  }
  return { planId: testingPlans[1].id, planName: testingPlans[1].name, status: "active", periodStart: "2026-10-01T00:00:00Z", renewsAt: "2026-11-01T00:00:00Z", usage, limits, features, entitlements, preview: true };
};

/** Show an illustrative feature matrix in both customer and admin catalog tabs. */
export const testingPlanFeatureLinks = (planId) => testingFeatures.map((feature, index) => ({
  id: `${planId}-${feature.id}`,
  plan_id: planId,
  feature_id: feature.id,
  feature,
  limit_value: feature.code === "rag_assistant" ? 500000 : feature.code === "tracked_competitors" ? 15 : null,
  preview: true,
}));
