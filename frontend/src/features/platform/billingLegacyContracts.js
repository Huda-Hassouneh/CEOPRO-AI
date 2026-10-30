// Presentation contracts for the original owner components. Python owns all prices.
const present = (v) => v !== null && v !== undefined && v !== '';
export function policyForLegacy(p = {}) {
  return { ...p, currency: p.quote_currency || 'USD',
    targetGrossMargin: p.target_gross_margin, fixedPlatformFee: p.fixed_platform_fee_usd,
    monthlyInfrastructureCost: p.monthly_shared_infrastructure_cost_usd,
    activePayingTenants: p.active_paying_tenant_count,
    roundingIncrement: p.upward_rounding_increment_usd,
    enforceVendorCostRatioFloor: p.enforce_vendor_cost_ratio_floor === true,
    maxVendorCostRevenueRatio: p.max_vendor_cost_revenue_ratio };
}
export function policyFromLegacy(p) {
  if (p.currency !== 'USD') throw new Error('CUSTOM-002 requires USD pricing.');
  const decimal = (name, value, lower, upper = Infinity, exclusive = false) => {
    if (!present(value) || !Number.isFinite(Number(value)) || Number(value) < lower ||
        (exclusive ? Number(value) >= upper : Number(value) > upper))
      throw new Error(`Enter a valid ${name}.`);
    return String(value);
  };
  if (!String(p.approvalEvidence || '').trim()) throw new Error('Approval evidence is required.');
  if (p.enforceVendorCostRatioFloor === true && !present(p.maxVendorCostRevenueRatio)) throw new Error('Vendor cost ratio is required when the floor is enabled.');
  const count = present(p.activePayingTenants) ? Number(p.activePayingTenants) : null;
  if (count !== null && (!Number.isSafeInteger(count) || count <= 0)) throw new Error('Active paying tenants must be a positive integer.');
  const infrastructure = decimal('shared infrastructure cost', p.monthlyInfrastructureCost, 0);
  if (Number(infrastructure) > 0 && count === null) throw new Error('Active paying tenant count is required for shared costs.');
  return {
    target_gross_margin: decimal('target margin', p.targetGrossMargin, 0, 1, true),
    enforce_vendor_cost_ratio_floor: p.enforceVendorCostRatioFloor === true,
    max_vendor_cost_revenue_ratio: present(p.maxVendorCostRevenueRatio) ? decimal('vendor cost ratio', p.maxVendorCostRevenueRatio, Number.MIN_VALUE, 1) : null,
    fixed_platform_fee_usd: decimal('platform fee', p.fixedPlatformFee, 0),
    upward_rounding_increment_usd: decimal('rounding increment', p.roundingIncrement, 0),
    monthly_shared_infrastructure_cost_usd: infrastructure,
    active_paying_tenant_count: count, approval_evidence: p.approvalEvidence.trim(),
  };
}
export function quoteForLegacy(q) {
  const rev = q.currentRevision || q.current_revision || q;
  const config = rev.configuration || {};
  const quantities = rev.featureQuantities || rev.feature_quantities || {};
  const terms = rev.commercialTerms || rev.commercial_terms || {};
  const snapshot = rev.pricingSnapshot || rev.pricing_snapshot || {};
  const calculation = snapshot.calculation || {};
  const enabled = config.enabledFeatures || [];
  const cadence = { hourly: 60, daily: 1440, weekly: 10080 }[config.refreshFrequency];
  return { ...q, ...calculation, id: q.quoteId || q.quote_id || q.id,
    tenantId: q.tenantId || q.tenant_id, tenant: { businessName: q.businessName || q.business_name || q.tenant?.businessName },
    name: config.requestLabel || q.customerName || q.customer_name || q.businessName || q.business_name || q.quoteId || q.quote_id,
    nameAr: config.requestLabelAr, description: config.requestDescription, descriptionAr: config.requestDescriptionAr,
    status: q.state, revision: rev.revisionNumber || rev.revision_number,
    configuration: config, quantities, currency: terms.currency || snapshot.currency || 'USD',
    updatedAt: q.updatedAt || q.updated_at, currentRevision: rev,
    pricingAvailable: Boolean(snapshot.calculationHash), pricingSnapshot: snapshot,
    finalPrice: ['approved','accepted'].includes(q.state) ? terms.monthlyPriceUsd || terms.monthly_price_usd : undefined,
    quoteFeatures: [...Object.entries(quantities).map(([featureId, limitValue]) => ({featureId, limitValue, estimatedUsage: limitValue})),
      ...enabled.map(featureId => ({featureId, estimatedUsage: 1, ...(featureId === 'competitor_management' && cadence ? {configuration:{monitoringFrequencyMinutes:cadence}} : {})}))],
    validUntil: rev.validUntil || rev.valid_until,
  };
}
export function subscriptionForLegacy(s, plans) {
  const plan = plans.find(p => p.id === s.plan_key);
  return { ...s, id: s.subscription_id, tenantId: s.tenant_id, tenant: {businessName:s.business_name},
    planId: s.plan_key, plan: {name: s.plan_name || plan?.name, name_ar:plan?.name_ar},
    billingPeriod:s.period_code, currentPeriodEnd:s.current_period_end, trialEnd:s.trial_end,
    cancelAtPeriodEnd:s.cancel_at_period_end,
    scheduledPlan:s.scheduled_plan_key ? plans.find(p=>p.id===s.scheduled_plan_key) || {name:s.scheduled_plan_key} : null,
    // The portfolio does not expose a transition type or effective date: never infer either.
  };
}
