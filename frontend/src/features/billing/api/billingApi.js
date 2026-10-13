import httpClient from '../../../shared/lib/httpClient.js';

// Real billing: the plan catalog, the company's subscription and usage come
// from the backend (/billing/*); payment happens on Stripe-hosted pages.

// Backend feature codes -> the keys the usage and plan screens render.
const LIMIT_KEYS = {
  tracked_products: ['products', 1],
  tracked_competitors: ['competitors', 1],
  rag_assistant: ['aiTokens', 1],
  marketing_image_generation: ['imageGenerations', 1],
  document_storage_mb: ['storageGb', 1 / 1024],
  document_extraction: ['documentProcessingMb', 1 / 1024],
  sentiment_analysis: ['sentimentRecords', 1],
  connected_data_sources: ['dataSources', 1],
};

// Plan modules (backend usage_plan_entitlements) shown on the plan cards.
export const PLAN_MODULES = Object.freeze(['market_intelligence', 'demand_prediction', 'competitor_management']);

export const BILLING_PERIODS = Object.freeze([
  { value: 'monthly', months: 1 },
  { value: 'three-months', months: 3 },
  { value: 'six-months', months: 6 },
]);

export function mapPlan(plan) {
  const limits = {};
  for (const [code, value] of Object.entries(plan.limits || {})) {
    // Only the plan terms customers see; internal budgets (e.g. web_searches) are skipped.
    if (!LIMIT_KEYS[code]) continue;
    const [key, factor] = LIMIT_KEYS[code];
    limits[key] = value === null ? null : Math.round(value * factor * 1000) / 1000;
  }
  const prices = Object.fromEntries((plan.prices || []).map((price) => [price.period_code, {
    amount: price.amount,
    currency: price.currency,
    months: price.interval_months,
    discountPercent: price.discount_percent,
    monthlyEquivalent: Math.round((price.amount / price.interval_months) * 100) / 100,
    purchasable: price.purchasable,
  }]));
  return {
    id: plan.plan_key,
    name: plan.name,
    monthlyPrice: plan.monthly_price,
    currency: plan.currency,
    trialDays: plan.trial_days,
    tier: plan.tier_level,
    selfServe: plan.self_serve,
    featured: plan.plan_key === 'growth',
    limits,
    entitlements: plan.entitlements || [],
    prices,
  };
}

const SUBSCRIPTION_STATUS = Object.freeze({
  trialing: 'trial', active: 'active', past_due: 'failed', payment_failed: 'failed', pending: 'failed',
  paused: 'failed', expired: 'expired', cancelled: 'expired',
});

export function errorReason(error) {
  return error?.response?.data?.detail?.reason || null;
}

export const billingApi = Object.freeze({
  getPlans: async () => {
    const { data } = await httpClient.get('/billing/plans');
    return { plans: (data.plans || []).map(mapPlan), paymentsEnabled: Boolean(data.payments_enabled) };
  },
  getSubscription: async () => {
    const { data } = await httpClient.get('/billing/subscription');
    return { ...data, status: SUBSCRIPTION_STATUS[data.status] || 'failed', billingStatus: data.status };
  },
  getInvoices: async () => (await httpClient.get('/billing/invoices')).data.invoices || [],
  checkout: async ({ planId, billingPeriod }) => (await httpClient.post('/billing/checkout', { plan_key: planId, period_code: billingPeriod })).data,
  openPortal: async () => (await httpClient.post('/billing/portal')).data,
  changePlan: async ({ planId, billingPeriod }) => (await httpClient.post('/billing/change-plan', { plan_key: planId, period_code: billingPeriod })).data,
  cancelScheduledChange: async () => (await httpClient.delete('/billing/scheduled-change')).data,
  cancel: async () => (await httpClient.post('/billing/cancel')).data,
  resume: async () => (await httpClient.post('/billing/resume')).data,
});
