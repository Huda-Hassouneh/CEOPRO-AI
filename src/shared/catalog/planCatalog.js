// Development/preview-only catalog used by the Platform Admin preview adapter.
// Customer-facing billing, onboarding, and landing pricing must use billingApi.getPlans()
// so production plan identity, prices, limits, and Stripe mappings remain server-owned.
export const BILLING_PERIODS = Object.freeze([
  { value: 'monthly', months: 1, discountPercent: 0 },
  { value: 'three-months', months: 3, discountPercent: 10 },
  { value: 'six-months', months: 6, discountPercent: 20 },
]);

export const PREVIEW_BILLING_CURRENCY = 'USD';

export function getBillingPeriod(billingPeriod, planId) {
  const period = BILLING_PERIODS.find((item) => item.value === billingPeriod) || BILLING_PERIODS[0];
  return { ...period, discountPercent: PREVIEW_PLANS[planId]?.discounts?.[period.value] ?? period.discountPercent };
}

export function getPreviewPlanPrice(planId, billingPeriod) {
  const plan = PREVIEW_PLANS[planId];
  const period = getBillingPeriod(billingPeriod, planId);
  if (!plan || plan.monthlyPrice === null) return null;

  const base = plan.monthlyPrice * period.months;
  const discount = base * (period.discountPercent / 100);
  const total = Number((base - discount).toFixed(2));
  return Object.freeze({
    billingPeriod: period.value,
    months: period.months,
    discountPercent: period.discountPercent,
    base,
    discount,
    total,
    monthlyEquivalent: Number((total / period.months).toFixed(2)),
    isMultiMonth: period.months > 1,
  });
}

export function formatPreviewUsd(amount, locale = 'en') {
  return new Intl.NumberFormat(locale === 'ar' ? 'ar-JO' : 'en-US', {
    style: 'currency',
    currency: PREVIEW_BILLING_CURRENCY,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export const PREVIEW_PLANS = Object.freeze({
  starter: {
    id: 'starter',
    nameKey: 'billing.plans.starter.name',
    actionKey: 'billing.plans.starter.action',
    monthlyPrice: 55,
    trialDays: 14,
    descriptionKey: 'billing.plans.starter.description',
    limits: { products: 250, competitors: 0, ragQueries: 100000, reports: 0, storageGb: 1 },
  },
  growth: {
    id: 'growth',
    nameKey: 'billing.plans.growth.name',
    actionKey: 'billing.plans.growth.action',
    monthlyPrice: 140,
    trialDays: 14,
    descriptionKey: 'billing.plans.growth.description',
    featured: true,
    limits: { products: 2000, competitors: 10, ragQueries: 500000, reports: 0, storageGb: 10 },
  },
  enterprise: {
    id: 'enterprise',
    nameKey: 'billing.plans.enterprise.name',
    actionKey: 'billing.plans.enterprise.action',
    monthlyPrice: 350,
    trialDays: 7,
    descriptionKey: 'billing.plans.enterprise.description',
    limits: { products: 10000, competitors: 50, ragQueries: 2000000, reports: 0, storageGb: 50 },
  },
  custom: {
    id: 'custom',
    nameKey: 'billing.plans.custom.name',
    actionKey: 'billing.plans.custom.action',
    monthlyPrice: null,
    trialDays: 0,
    descriptionKey: 'billing.plans.custom.description',
    featureKeys: ['everythingGrowth', 'customLimits', 'support', 'largeTeams'],
  },
});

export function getPreviewPlan(planId) {
  return PREVIEW_PLANS[planId] || PREVIEW_PLANS.growth;
}

export function getPlanFeatureRows(planOrId) {
  const plan = typeof planOrId === 'string' ? getPreviewPlan(planOrId) : planOrId;
  if (plan.id === 'custom') return plan.featureKeys.map((key) => ({ key, value: '' }));
  const formatLimit = (value) => value === null ? '∞' : new Intl.NumberFormat('en-US').format(value);

  return [
    { key: 'products', value: formatLimit(plan.limits.products) },
    { key: 'competitors', value: formatLimit(plan.limits.competitors) },
    { key: 'ragQueries', value: formatLimit(plan.limits.ragQueries) },
    { key: 'reports', value: formatLimit(plan.limits.reports) },
    { key: 'storage', value: `${formatLimit(plan.limits.storageGb)} GB` },
  ];
}

export const CUSTOM_PLAN_LIMITS = Object.freeze({
  products: { min: 10, max: 5000, step: 10, defaultValue: 500, icon: 'products' },
  competitors: { min: 5, max: 200, step: 5, defaultValue: 20, icon: 'competitors' },
  ragQueries: { min: 100, max: 10000, step: 100, defaultValue: 1000, icon: 'ragQueries' },
  reports: { min: 10, max: 5000, step: 10, defaultValue: 100, icon: 'reports' },
  storageGb: { min: 5, max: 500, step: 5, defaultValue: 20, icon: 'storageGb' },
  teamMembers: { min: 1, max: 100, step: 1, defaultValue: 10, icon: 'teamMembers' },
});

export const DEFAULT_CUSTOM_PLAN = Object.freeze({
  ...Object.fromEntries(Object.entries(CUSTOM_PLAN_LIMITS).map(([key, value]) => [key, value.defaultValue])),
  integrations: 'none',
  updateFrequency: 'daily',
});

export const CUSTOM_PLAN_SUMMARY_FIELDS = Object.freeze([
  'products', 'competitors', 'ragQueries', 'reports', 'storageGb', 'teamMembers', 'integrations', 'updateFrequency',
]);

export const PREVIEW_CUSTOM_QUOTE = Object.freeze({
  amount: 149,
  currency: 'USD',
  interval: 'month',
  preview: true,
});

// Preview-adapter fields. Production customer entitlements come from backend feature codes.
export const FEATURE_KEYS = Object.freeze(['marketIntelligence', 'demandPrediction', 'pricingIntelligence', 'sentiment', 'ragAssistant', 'reports', 'dataIntegration']);
export const LIMIT_KEYS = Object.freeze(['products', 'competitors', 'ragQueries', 'reports', 'storageGb']);

const previewNames = {
  starter: { en: 'Starter', ar: 'البداية' },
  growth: { en: 'Growth', ar: 'النمو' },
  enterprise: { en: 'Enterprise', ar: 'المؤسسات' },
  custom: { en: 'Custom', ar: 'مخصصة' },
};
const previewDescriptions = {
  starter: {
    en: 'Core analytics, basic ingestion, and limited AI capacity.',
    ar: 'تحليلات أساسية وتكامل بيانات أساسي وسعة محدودة للذكاء الاصطناعي.',
  },
  growth: {
    en: 'Forecasting, competitor intelligence, and expanded AI capacity.',
    ar: 'تنبؤ بالطلب وذكاء المنافسين وسعة موسعة للذكاء الاصطناعي.',
  },
  enterprise: {
    en: 'Higher workloads, advanced integrations, and faster monitoring.',
    ar: 'أحمال عمل أعلى وتكاملات متقدمة ومراقبة أسرع.',
  },
  custom: {
    en: 'Capacity tailored to your business.',
    ar: 'سعة مصممة لاحتياجات شركتك.',
  },
};

for (const plan of Object.values(PREVIEW_PLANS)) {
  Object.assign(plan, {
    status: 'active',
    currency: 'USD',
    version: 1,
    updatedAt: null,
    name: previewNames[plan.id],
    description: previewDescriptions[plan.id],
    billingOptions: BILLING_PERIODS.map((period) => period.value),
    discounts: Object.fromEntries(BILLING_PERIODS.map((period) => [period.value, period.discountPercent])),
    entitlements: Object.fromEntries(FEATURE_KEYS.map((key) => [key, null])),
  });
}

export function replacePreviewPlan(plan) {
  if (!PREVIEW_PLANS[plan.id]) throw new Error('Unknown plan');
  Object.assign(PREVIEW_PLANS[plan.id], structuredClone(plan));
}

export const planCatalogApi = {
  getPlans: async () => ({ plans: structuredClone(Object.values(PREVIEW_PLANS)), preview: true }),
};
