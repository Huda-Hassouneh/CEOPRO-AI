// Presentation adapter only. Values and units come from the Python catalog.
export function toOriginalPlan(plan) {
  if (typeof plan?.name === 'string') return plan;
  const meta = plan.feature_catalog || {};
  const features = {};
  for (const [code, value] of Object.entries(plan.rawLimits || {})) {
    if (['web_searches', 'rag_assistant'].includes(code)) continue;
    if (code === 'tracked_competitors' && plan.id !== 'custom') continue;
    const item = meta[code] || {};
    features[code] = { ...item, type: 'limit', limitValue: value,
      name: item.name || code.replaceAll('_', ' '), unit: item.unit || '' };
  }
  for (const code of plan.entitlements || []) {
    const item = meta[code] || {};
    features[code] = { ...item, type: 'boolean', name: item.name || code.replaceAll('_', ' ') };
  }
  return { ...plan, name: plan.name?.en || plan.id, name_ar: plan.name?.ar,
    tier_level: plan.tier, basePrice: plan.monthlyPrice, isActive: plan.selfServe,
    trialPeriodDays: plan.trialDays, features,
    pricingOptions: Object.entries(plan.prices || {}).map(([period, value]) => ({
      ...value, period, totalPrice: value.amount, intervalUnit: 'month',
      intervalCount: value.months, months: value.months,
    })),
  };
}
export function toOriginalSubscription(raw, plans = []) {
  if (!raw?.assigned && !raw?.hasSubscription && !raw?.trialUsed) return null;
  return { ...raw, status: raw.billingStatus || raw.status, hasStripeSubscription: raw.hasSubscription,
    plan: plans.find((plan) => plan.id === raw.planId),
    currentPeriodStart: raw.periodStart, currentPeriodEnd: raw.periodEnd,
    trialEnd: raw.trialEndsAt, trialEndsAt: raw.trialEndsAt,
    scheduledPlanId: raw.scheduledChange?.planId, scheduledBillingPeriod: raw.scheduledChange?.billingPeriod,
    scheduledPlan: plans.find((plan) => plan.id === raw.scheduledChange?.planId) };
}
export function toOriginalUsage(raw, plans = []) {
  const metadata = plans.find((plan) => plan.id === raw.planId)?.features || {};
  const usage = {}, limits = {}, features = {};
  for (const item of raw.features || []) {
    const code = item.feature_code;
    if (['web_searches', 'rag_assistant'].includes(code)) continue;
    if (code === 'tracked_competitors' && raw.planId !== 'custom') continue;
    usage[code] = item.current_usage; limits[code] = item.limit;
    features[code] = { ...metadata[code], ...item, type: 'limit', name: metadata[code]?.name || code.replaceAll('_', ' ') };
  }
  for (const code of raw.entitlements || []) {
    features[code] = { ...metadata[code], type: 'boolean', name: metadata[code]?.name || code.replaceAll('_', ' ') };
    limits[code] = true; usage[code] = true;
  }
  return { usage, limits, features, planName: raw.planName };
}
export function toOriginalInvoice(invoice) {
  return { ...invoice, id: invoice.invoice_id, invoiceNumber: invoice.invoice_number || invoice.invoice_id,
    date: invoice.paid_at || invoice.created_at, paymentStatus: invoice.status === 'succeeded' ? 'paid' : invoice.status,
    type: 'subscription', pdfUrl: invoice.invoice_pdf_url, hostedUrl: invoice.hosted_invoice_url };
}
