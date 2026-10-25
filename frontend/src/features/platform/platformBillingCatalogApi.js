import { customOffersApi } from '../billing/api/customOffersApi.js';
import { platformBillingApi } from './platformBillingApi.js';

const unavailable = (name) => Promise.reject(Object.assign(
  new Error(`The Python billing API does not expose ${name}; this control is read-only.`),
  { code: 'BACKEND_CAPABILITY_UNAVAILABLE' },
));
const list = (response, key) => Array.isArray(response?.[key]) ? response[key] : [];
const wrap = (data) => ({ data });

export function createPlatformBillingCatalogApi({ billing = platformBillingApi, offers = customOffersApi } = {}) {
  const plans = async () => list(await billing.view('plans'), 'plans').map((p) => ({
    ...p,
    id: p.plan_key,
    name: p.display_name,
    name_ar: p.display_name_ar,
    tier_level: p.tier_level,
    basePrice: p.monthly_price,
    currency: p.currency || 'USD',
    trialPeriodValue: p.trial_days,
    isActive: p.is_active,
    pricingOptions: (p.prices || []).map((price) => ({
      period: price.period_code,
      intervalCount: price.interval_months,
      price: price.unit_amount,
      currency: price.currency,
    })),
  }));
  const rates = async () => list(await billing.rates(), 'cost_rates').map((r) => ({
    ...r,
    id: r.cost_rate_id,
    vendor: r.provider,
    service: r.operation,
    billingUnit: r.unit,
    unitCost: r.unit_cost_usd,
    currency: r.currency || 'USD',
    verificationStatus: r.verification_status || (r.verified_at && r.verification_evidence ? 'confirmed' : 'unconfirmed'),
    source: r.source,
  }));

  return Object.freeze({
    getPlans: async () => wrap(await plans()),
    getFeatures: async () => {
      const catalog = await offers.getConfigurator();
      return wrap((catalog.features || []).map((feature) => ({
        id: feature.featureCode,
        code: feature.featureCode,
        name: feature.featureCode,
        type: 'limit',
        unit: feature.unit,
        aggregation: feature.aggregationType,
        resetCycle: feature.resetCycle,
      })));
    },
    getPlanFeatures: async (planId) => {
      const plan = (await plans()).find((item) => item.id === planId);
      return wrap((plan?.feature_limits || []).map((item) => ({
        id: `${planId}:${item.feature_code}`,
        planId,
        featureId: item.feature_code,
        limitValue: item.limit_value,
        feature: { id: item.feature_code, code: item.feature_code, name: item.feature_code, type: 'limit', unit: item.unit },
      })));
    },
    getPromoCodes: () => unavailable('promotion-code administration'),
    getSubscriptions: async () => wrap(list(await billing.view('subscriptions'), 'subscriptions')),
    getCustomPlans: async () => wrap(list(await billing.view('contracts'), 'contracts').map((c) => ({
      ...c,
      id: c.tenant_id,
      tenant: { businessName: c.business_name },
      name: c.contract_ref,
      isActive: c.assignment_status === 'active',
      features: c.included_features,
    }))),
    getCustomPlanQuotes: async () => wrap(list(await billing.quotes(), 'quotes').map((q) => ({
      ...q,
      id: q.quoteId || q.quote_id,
      tenantId: q.tenantId || q.tenant_id,
      tenant: { businessName: q.businessName || q.business_name },
      name: q.customerName || q.customer_name || q.businessName || q.business_name || q.quoteId || q.quote_id,
      nameAr: q.customerNameAr || q.customer_name_ar,
      status: q.state,
      revision: q.currentRevision?.revisionNumber || q.revision_number,
      updatedAt: q.updatedAt || q.updated_at,
      currentRevision: q.currentRevision,
      configuration: q.currentRevision?.configuration || q.configuration,
      quantities: q.currentRevision?.featureQuantities || q.feature_quantities,
      currency: q.currentRevision?.commercialTerms?.currency || q.currentRevision?.commercialTerms?.currencyCode,
    }))),
    getCustomPlanPricingPolicy: async () => ({ data: {} }),
    getVendorRates: async () => wrap(await rates()),
    getTenants: () => unavailable('tenant search in quote creation'),
    createPlan: () => unavailable('plan creation'),
    updatePlan: () => unavailable('plan mutation'),
    createPromoCode: () => unavailable('promotion-code creation'),
    updatePromoCode: () => unavailable('promotion-code mutation'),
    linkPromoCodeToPlan: () => unavailable('promotion-code assignment'),
    createFeature: () => unavailable('feature catalog mutation'),
    updateFeature: () => unavailable('feature catalog mutation'),
    removeFeature: () => unavailable('feature catalog mutation'),
    linkFeatureToPlan: () => unavailable('plan quota mutation'),
    unlinkFeatureFromPlan: () => unavailable('plan quota mutation'),
    updatePlanFeatureLimit: () => unavailable('plan quota mutation'),
    setCustomPlanActive: () => unavailable('custom-contract status mutation'),
    createCustomPlanQuote: () => unavailable('legacy quote creation'),
    updateCustomPlanQuote: () => unavailable('legacy quote editing'),
    approveCustomPlanQuote: (id, body) => billing.approveQuote(id, body),
    calculateCustomPlanQuote: (id) => billing.calculateQuote(id),
    rejectCustomPlanQuote: (id, body) => billing.rejectQuote(id, body),
    sendCustomPlanQuote: () => unavailable('email quote delivery; approved offers are available in-app'),
    updateCustomPlanPricingPolicy: () => unavailable('legacy mutable pricing policy; use versioned Python policy administration'),
    createVendorRate: () => unavailable('legacy vendor rate mutation; use versioned Python cost rates'),
    updateVendorRate: () => unavailable('legacy vendor rate mutation; use versioned Python cost rates'),
  });
}

export const platformBillingCatalogApi = createPlatformBillingCatalogApi();