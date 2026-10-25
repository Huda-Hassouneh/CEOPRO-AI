import { customOffersApi } from '../billing/api/customOffersApi.js';
import { platformBillingApi } from './platformBillingApi.js';
const unavailable = (name) => Promise.reject(Object.assign(new Error(`The Python billing API does not expose ${name}; this control is unavailable.`), { code: 'BACKEND_CAPABILITY_UNAVAILABLE' }));
const list = (response, key) => Array.isArray(response?.[key]) ? response[key] : [];
const wrap = (data) => ({ data });
const promoTerms = (p) => p?.terms || {};
const promoForUi = (p) => {
  const terms = promoTerms(p);
  return { ...p, id: p.promotion_id, currency: terms.currency, discountType: terms.discount_type === 'percent' ? 'percentage' : terms.discount_type,
    discountValue: Number(terms.discount_value || 0), maxUses: terms.max_uses, maxUsesPerUser: terms.max_uses_per_tenant,
    startsAt: terms.starts_at, expiresAt: terms.expires_at, isActive: p.status === 'active', planKeys: p.plan_keys || [],
    status: p.status, missingTerms: p.missing_terms || [] };
};
const promoPayload = (p, planKeys = []) => ({
  code: String(p.code || '').trim().toUpperCase(), name: String(p.code || '').trim().toUpperCase(), description: '',
  reason: 'Platform owner promotion administration', plan_keys: planKeys,
  terms: {
    discount_type: p.discountType === 'percentage' ? 'percent' : p.discountType,
    discount_value: Number(p.discountValue), starts_at: p.startsAt || null, expires_at: p.expiresAt || null,
    max_uses: p.maxUses == null ? null : Number(p.maxUses),
    max_uses_per_tenant: p.maxUsesPerUser == null ? null : Number(p.maxUsesPerUser),
    invoice_scope: 'initial_subscription',
    ...(p.currency ? { currency: String(p.currency).toUpperCase() } : {}),
    ...(p.stripe_coupon_id ? { stripe_coupon_id: p.stripe_coupon_id } : {}),
    ...(p.stripe_promotion_code_id ? { stripe_promotion_code_id: p.stripe_promotion_code_id } : {}),
  }
});
export function createPlatformBillingCatalogApi({ billing = platformBillingApi, offers = customOffersApi } = {}) {
  const plans = async () => list(await billing.view('plans'), 'plans').map((p) => ({ ...p, id: p.plan_key, name: p.display_name, name_ar: p.display_name_ar, tier_level: p.tier_level, basePrice: p.monthly_price, currency: p.currency || 'USD', trialPeriodValue: p.trial_days, isActive: p.is_active, pricingOptions: (p.prices || []).map((price) => ({ period: price.period_code, intervalCount: price.interval_months, price: price.unit_amount, currency: price.currency })) }));
  const rates = async () => list(await billing.rates(), 'cost_rates').map((r) => ({ ...r, id: r.cost_rate_id, vendor: r.provider, service: r.operation, billingUnit: r.unit, unitCost: r.unit_cost_usd, currency: r.currency || 'USD', verificationStatus: r.verification_status || (r.verified_at && r.verification_evidence ? 'confirmed' : 'unconfirmed'), source: r.source }));
  const promotions = async () => { if (typeof billing.promotions !== 'function') return unavailable('promotion-code administration'); return list(await billing.promotions(), 'items').map(promoForUi); };
  return Object.freeze({
    getPlans: async () => wrap(await plans()),
    getFeatures: async () => { const catalog = await offers.getConfigurator(); return wrap((catalog.features || []).map((f) => ({ id: f.featureCode, code: f.featureCode, name: f.featureCode, type: 'limit', unit: f.unit, aggregation: f.aggregationType, resetCycle: f.resetCycle }))); },
    getPlanFeatures: async (planId) => { const plan = (await plans()).find((item) => item.id === planId); return wrap((plan?.feature_limits || []).map((item) => ({ id: `${planId}:${item.feature_code}`, planId, featureId: item.feature_code, limitValue: item.limit_value, feature: { id: item.feature_code, code: item.feature_code, name: item.feature_code, type: 'limit', unit: item.unit } }))); },
    getPromoCodes: async () => wrap(await promotions()),
    getSubscriptions: async () => wrap(list(await billing.view('subscriptions'), 'subscriptions')),
    getCustomPlans: async () => wrap(list(await billing.view('contracts'), 'contracts').map((c) => ({ ...c, id: c.tenant_id, tenant: { businessName: c.business_name }, name: c.contract_ref, isActive: c.assignment_status === 'active', features: c.included_features }))),
        getCustomPlanQuotes: async () => wrap(((await billing.quotes()).quotes || []).map((q) => ({
      ...q,
      id: q.quoteId || q.quote_id,
      tenantId: q.tenantId || q.tenant_id,
      tenant: { businessName: q.businessName || q.business_name },
      name: q.customerName || q.customer_name || q.businessName || q.business_name || q.quoteId || q.quote_id,
      nameAr: q.customerNameAr || q.customer_name_ar,
      status: q.state,
      revision: q.currentRevision?.revisionNumber || q.revision_number,
      updatedAt: q.updatedAt || q.updated_at,
      currentRevision: q.currentRevision || q.current_revision,
      configuration: q.currentRevision?.configuration || q.current_revision?.configuration || q.configuration,
      quantities: q.currentRevision?.featureQuantities || q.current_revision?.feature_quantities || q.feature_quantities,
      currency: q.currentRevision?.commercialTerms?.currency || q.current_revision?.commercial_terms?.currency,
    }))),
    getCustomPlanPricingPolicy: async () => ({ data: await billing.policies() }),
    getVendorRates: async () => wrap(await rates()),
    getTenants: () => unavailable('tenant search for manual contract creation'),
    createPlan: () => unavailable('plan creation'), updatePlan: () => unavailable('plan mutation'),
    createPromoCode: async (payload) => {
      if (payload.discountType === 'fixed_amount' && !payload.currency) {
        const currencies = [...new Set((await plans()).map((p) => String(p.currency || '').toUpperCase()).filter(Boolean))];
        if (currencies.length !== 1) throw new Error('Choose a currency for fixed-amount promotions; the Python API requires an explicit currency.');
        payload = { ...payload, currency: currencies[0] };
      }
      const saved = await billing.createPromotionDraft(promoPayload(payload));
      return saved;
    },
    updatePromoCode: async (id, payload) => {
      const current = (await promotions()).find((p) => p.id === id);
      if (!current) throw new Error('Promotion draft not found. Refresh the list.');
      if (payload.isActive === false && current.status === 'active') return billing.disablePromotion(id, 'Disabled by Platform Owner.');
      if (payload.isActive === true && current.status !== 'active') throw new Error('Python stores new promotions as drafts. Activation requires verified Stripe coupon and promotion-code references; no provider operation was performed.');
      return billing.updatePromotionDraft(id, promoPayload({ ...current, ...payload, discountType: payload.discountType || current.discountType, discountValue: payload.discountValue ?? current.discountValue, startsAt: payload.startsAt || current.startsAt, expiresAt: payload.expiresAt || current.expiresAt, maxUses: payload.maxUses ?? current.maxUses, maxUsesPerUser: payload.maxUsesPerUser ?? current.maxUsesPerUser }, current.planKeys));
    },
    linkPromoCodeToPlan: async ({ promoCodeId, planId }) => {
      const current = (await promotions()).find((p) => p.id === promoCodeId);
      if (!current) throw new Error('Promotion draft not found. Refresh the list.');
      if (current.status !== 'draft') throw new Error('Only draft promotions can be edited.');
      return billing.updatePromotionDraft(promoCodeId, promoPayload(current, [...new Set([...current.planKeys, planId])]));
    },
    createFeature: () => unavailable('canonical feature catalog mutation'), updateFeature: () => unavailable('canonical feature catalog mutation'), removeFeature: () => unavailable('canonical feature catalog mutation'),
    linkFeatureToPlan: () => unavailable('plan quota mutation'), unlinkFeatureFromPlan: () => unavailable('plan quota mutation'), updatePlanFeatureLimit: () => unavailable('plan quota mutation'),
    setCustomPlanActive: () => unavailable('custom-contract status mutation'), createCustomPlanQuote: () => unavailable('legacy quote creation'), updateCustomPlanQuote: () => unavailable('legacy quote editing'),
    approveCustomPlanQuote: (id, body) => billing.approveQuote(id, body), calculateCustomPlanQuote: (id) => billing.calculateQuote(id), rejectCustomPlanQuote: (id, body) => billing.rejectQuote(id, body),
    sendCustomPlanQuote: () => unavailable('email quote delivery; offers are available in-app'),
    updateCustomPlanPricingPolicy: () => unavailable('mutable legacy pricing; use versioned Python policy administration'),
    createVendorRate: () => unavailable('legacy vendor rate mutation; use versioned Python cost rates'), updateVendorRate: () => unavailable('legacy vendor rate mutation; use versioned Python cost rates'),
  });
}
export const platformBillingCatalogApi = createPlatformBillingCatalogApi();

