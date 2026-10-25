import { customOffersApi } from '../billing/api/customOffersApi.js';
import { platformBillingApi } from './platformBillingApi.js';
const unavailable = (name) => Promise.reject(Object.assign(new Error(`The Python billing API does not expose ${name}; this control is unavailable.`), { code: 'BACKEND_CAPABILITY_UNAVAILABLE' }));
const list = (response, key) => Array.isArray(response?.[key]) ? response[key] : [];
const wrap = (data) => ({ data });
const idempotencyKey = () => globalThis.crypto?.randomUUID?.() ?? `keel-owner-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const MODULE_CODES = new Set(['market_intelligence', 'demand_prediction', 'competitor_management']);
function customQuoteBody(payload, key) {
  const selected = payload.features || [];
  const enabledFeatures = selected.map((feature) => String(feature.featureId || feature.code || feature.id))
    .filter((code) => MODULE_CODES.has(code));
  const featureQuantities = {};
  for (const feature of selected) {
    const code = String(feature.featureId || feature.code || feature.id);
    if (MODULE_CODES.has(code)) continue;
    if (!Number.isInteger(feature.limitValue) || feature.limitValue < 0)
      throw new Error(`Enter a nonnegative integer allowance for ${code}.`);
    featureQuantities[code] = feature.limitValue;
  }
  const competitor = selected.find((feature) => String(feature.featureId || feature.code || feature.id) === 'competitor_management');
  const minutes = competitor?.configuration?.monitoringFrequencyMinutes;
  const refreshFrequency = minutes == null ? null : ({ 60: 'hourly', 1440: 'daily', 10080: 'weekly' })[Number(minutes)];
  if (competitor && !refreshFrequency)
    throw new Error('Python Custom Plans support hourly, daily, or weekly competitor monitoring cadence.');
  if (!enabledFeatures.length && !Object.values(featureQuantities).some((value) => value > 0))
    throw new Error('Select an included module or a positive allowance before submitting the quote.');
  return { tenant_id: payload.tenantId, idempotency_key: key,
    configuration: { enabledFeatures, refreshFrequency,
      ...(payload.name ? { requestLabel: String(payload.name).trim().slice(0, 80) } : {}),
      ...(payload.name_ar ? { requestLabelAr: String(payload.name_ar).trim().slice(0, 80) } : {}),
      ...(payload.description ? { requestDescription: String(payload.description).trim().slice(0, 1000) } : {}),
      ...(payload.description_ar ? { requestDescriptionAr: String(payload.description_ar).trim().slice(0, 1000) } : {}) }, feature_quantities: featureQuantities,
    // Historical client economics are not authoritative Python inputs.
    commercial_terms: {}, economic_inputs: {}, fx_evidence: {} };
}
const quoteId = (quote) => quote?.quote_id || quote?.quoteId || quote?.id;
const quoteRevision = (quote) => quote?.currentRevision || quote?.current_revision || {};
const quoteNumber = (quote) => Number(quote?.revision_number || quote?.revisionNumber || quoteRevision(quote).revision_number || quoteRevision(quote).revisionNumber || 1);
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
  reason: p.approvalReason || 'Platform owner promotion administration', plan_keys: planKeys,
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
  const rates = async () => {
    const rows = list(await billing.rates(), 'cost_rates');
    const { policies = [] } = await billing.policies();
    const bindings = [];
    for (const policy of policies) {
      const result = await billing.bindings(policy.policy_version_id);
      bindings.push(...list(result, 'bindings').map((binding) => ({ ...binding, policy_version_id: policy.policy_version_id, policy_status: policy.status })));
    }
    return rows.map((rate) => {
      const binding = bindings.find((item) => item.cost_rate_id === rate.cost_rate_id);
      return { ...rate, id: rate.cost_rate_id, vendor: rate.provider, service: rate.operation,
        billingUnit: rate.unit, unitCost: rate.unit_cost_usd, currency: 'USD',
        budgetKind: rate.budget_kind, verifiedAt: rate.verified_at,
        effectiveFrom: rate.effective_from, effectiveTo: rate.effective_to,
        verificationStatus: rate.verification_evidence ? 'confirmed' : 'unconfirmed', source: rate.source,
        ...(binding ? { featureId: binding.feature_code, policyVersionId: binding.policy_status === 'draft' ? binding.policy_version_id : '',
          usageBasis: binding.usage_basis, unitsPerFeatureUnit: binding.units_per_feature_unit,
          operationalMultiplier: binding.operational_multiplier, variabilityReserve: binding.variability_reserve,
          metadata: { usageAssumption: binding.usage_assumption || {} } } : {}),
      };
    });
  };
  const promotions = async () => { if (typeof billing.promotions !== 'function') return unavailable('promotion-code administration'); return list(await billing.promotions(), 'items').map(promoForUi); };
  const saveVendorRate = async (payload) => {
    if (String(payload.currency || '').toUpperCase() !== 'USD') throw new Error('Python Custom Plan cost schedules currently require USD rates; no currency conversion was applied.');
    if (payload.verificationStatus !== 'confirmed') throw new Error('A verified provider rate is required. Select Confirmed only when the source evidence supports it.');
    const unit = String(payload.billingUnit || '').trim().toLowerCase();
    const validUnits = new Set(['request', 'record', 'page', 'input_token', 'output_token', 'cache_read_token', 'cache_write_token', 'image']);
    if (!validUnits.has(unit)) throw new Error(`Unsupported Python cost unit: ${unit || '(empty)'}. Use request, record, page, input_token, output_token, cache_read_token, cache_write_token, or image.`);
    return billing.saveVendorRate({
      budget_kind: payload.budgetKind, provider: payload.vendor, operation: payload.service, unit,
      unit_cost_usd: Number(payload.unitCost), source: payload.source, verification_evidence: payload.source,
      verified_at: payload.verifiedAt, effective_from: payload.effectiveFrom, effective_to: payload.effectiveTo || null,
      supersedes_rate_id: payload.supersedesRateId || null,
      policy_version_id: payload.featureId ? payload.policyVersionId : null, feature_code: payload.featureId || null,
      usage_basis: payload.usageBasis, units_per_feature_unit: Number(payload.unitsPerFeatureUnit ?? payload.unitsPerCompetitorCheck ?? 1),
      operational_multiplier: Number(payload.operationalMultiplier), variability_reserve: Number(payload.variabilityReserve),
      usage_assumption: payload.metadata?.usageAssumption || {}, required_for_price: true,
    });
  };
  return Object.freeze({
    getPlans: async () => wrap(await plans()),
    getFeatures: async () => {
      const catalog = await offers.getConfigurator();
      const numeric = (catalog.features || []).map((f) => ({ id: f.featureCode, code: f.featureCode, name: f.featureCode, type: 'limit', unit: f.unit, aggregationType: f.aggregationType, resetCycle: f.resetCycle }));
      const modules = (catalog.modules || []).map((f) => ({ id: f.featureCode, code: f.featureCode, name: f.featureCode, type: 'boolean', unit: '', aggregationType: 'max', resetCycle: 'lifetime' }));
      return wrap([...numeric, ...modules]);
    },
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
    getCustomPlanQuote: async (id) => billing.quote(id),
    createCustomPlanQuote: async (payload) => {
      if (!payload.tenantId) throw new Error('Select the customer tenant for this quote.');
      const created = await billing.createQuote(customQuoteBody(payload, idempotencyKey()));
      const id = quoteId(created);
      if (!id) throw new Error('The Python API did not return a quote identity. Refresh the quote list before retrying.');
      await billing.submitQuote(id, { expected_revision: 1, idempotency_key: idempotencyKey() });
      return wrap({ id, quote_id: id, state: 'submitted' });
    },
    updateCustomPlanQuote: async (id, payload) => {
      const existing = await billing.quote(id);
      const revision = quoteNumber(existing);
      const revised = await billing.reviseQuote(id, { ...customQuoteBody(payload, idempotencyKey()), expected_revision: revision });
      if ((existing.state || 'draft') === 'draft')
        await billing.submitQuote(id, { expected_revision: revision + 1, idempotency_key: idempotencyKey() });
      return wrap({ id, quote_id: id, revision: revised.revision_number || revision + 1, state: 'submitted' });
    },
    approveCustomPlanQuote: async (id, body = {}) => {
      const quote = await billing.quote(id);
      const reference = String(body.approvalReference || body.approval_reference || '').trim();
      if (!reference) throw new Error('An approval reference is required. Use the Python quote review action; prices cannot be overridden from this form.');
      return billing.approveQuote(id, { expected_revision: quoteNumber(quote), idempotency_key: idempotencyKey(), approval_reference: reference });
    },
    rejectCustomPlanQuote: async (id, body = {}) => {
      const quote = await billing.quote(id);
      return billing.rejectQuote(id, { expected_revision: quoteNumber(quote), idempotency_key: idempotencyKey(), ...body });
    },
    sendCustomPlanQuote: async (id) => {
      const quote = await billing.quote(id);
      if (quote.state !== 'approved') throw new Error('Only an approved offer is available to the customer.');
      return { quote_id: id, state: quote.state, available_in_app: true };
    },
    getCustomPlanPricingPolicy: async () => ({ data: await billing.policies() }),
    getVendorRates: async () => wrap(await rates()),
    getTenants: async () => wrap(list(await billing.companies(100, 0), 'items').map((tenant) => ({ ...tenant, id: tenant.tenant_id, businessName: tenant.business_name }))),
    createPlan: () => unavailable('plan creation'), updatePlan: () => unavailable('plan mutation'),
    createPromoCode: async (payload) => {
      if (payload.discountType === 'fixed_amount' && !payload.currency) {
        const catalog = await plans();
        const selected = catalog.find((plan) => plan.id === payload.planKey);
        const currencies = [...new Set((selected ? [selected] : catalog).map((p) => String(p.currency || '').toUpperCase()).filter(Boolean))];
        if (currencies.length !== 1) throw new Error('Select one eligible plan before creating a fixed-amount promotion so the backend can bind its currency.');
        payload = { ...payload, currency: currencies[0] };
      }
      const saved = await billing.createPromotionDraft(promoPayload(payload, payload.planKey ? [payload.planKey] : []));
      if (payload.isActive) return billing.activatePromotion(saved.promotion_id, {
        approval_reference: payload.approvalReference,
        reason: payload.approvalReason,
      });
      return saved;
    },
    updatePromoCode: async (id, payload) => {
      const current = (await promotions()).find((p) => p.id === id);
      if (!current) throw new Error('Promotion draft not found. Refresh the list.');
      const sameInstant = (left, right) => !left && !right || Boolean(left && right && Date.parse(left) === Date.parse(right));
      const changedTerms = (payload.discountType && payload.discountType !== current.discountType)
        || (payload.discountValue != null && Number(payload.discountValue) !== current.discountValue)
        || (payload.maxUses != null && Number(payload.maxUses) !== Number(current.maxUses))
        || (payload.maxUsesPerUser != null && Number(payload.maxUsesPerUser) !== Number(current.maxUsesPerUser))
        || (payload.startsAt && !sameInstant(payload.startsAt, current.startsAt))
        || (payload.expiresAt && !sameInstant(payload.expiresAt, current.expiresAt))
        || (payload.planKey && !(current.planKeys || []).includes(payload.planKey));
      if (current.status !== 'draft' && changedTerms)
        throw new Error('Active or disabled promotion terms are immutable; create a new promotion to change them.');
      if (payload.isActive === false && current.status === 'active') return billing.disablePromotion(id, 'Disabled by Platform Owner.');
      if (payload.isActive === true && current.status === 'disabled') {
        return billing.activatePromotion(id, { approval_reference: payload.approvalReference, reason: payload.approvalReason });
      }
      if (current.status !== 'draft')
        throw new Error('Only promotion drafts can be edited. Choose Activate or Deactivate to change this promotion status.');
      const next = { ...current, ...payload, discountType: payload.discountType || current.discountType,
        discountValue: payload.discountValue ?? current.discountValue, startsAt: payload.startsAt || current.startsAt,
        expiresAt: payload.expiresAt || current.expiresAt, maxUses: payload.maxUses ?? current.maxUses,
        maxUsesPerUser: payload.maxUsesPerUser ?? current.maxUsesPerUser };
      const planKeys = [...new Set([...(current.planKeys || []), ...(payload.planKey ? [payload.planKey] : [])])];
      const saved = await billing.updatePromotionDraft(id, promoPayload(next, planKeys));
      if (payload.isActive === true) return billing.activatePromotion(id, {
        approval_reference: payload.approvalReference,
        reason: payload.approvalReason,
      });
      return saved;
    },
    linkPromoCodeToPlan: async ({ promoCodeId, planId }) => {
      const current = (await promotions()).find((p) => p.id === promoCodeId);
      if (!current) throw new Error('Promotion draft not found. Refresh the list.');
      if (current.status !== 'draft') throw new Error('Only draft promotions can be edited.');
      return billing.updatePromotionDraft(promoCodeId, promoPayload(current, [...new Set([...current.planKeys, planId])]));
    },
    createFeature: () => unavailable('canonical feature catalog mutation'), updateFeature: () => unavailable('canonical feature catalog mutation'), removeFeature: () => unavailable('canonical feature catalog mutation'),
    linkFeatureToPlan: () => unavailable('plan quota mutation'), unlinkFeatureFromPlan: () => unavailable('plan quota mutation'), updatePlanFeatureLimit: () => unavailable('plan quota mutation'),
    setCustomPlanActive: () => unavailable('custom-contract status mutation; contract status is driven by approved billing and entitlement authorities'),
    calculateCustomPlanQuote: (id) => billing.calculateQuote(id),
    updateCustomPlanPricingPolicy: () => unavailable('mutable legacy pricing; use versioned Python policy administration'),
    createVendorRate: (payload) => saveVendorRate(payload), updateVendorRate: (rateId, payload) => saveVendorRate({ ...payload, supersedesRateId: rateId }),
  });
}
export const platformBillingCatalogApi = createPlatformBillingCatalogApi();

