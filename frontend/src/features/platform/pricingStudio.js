// Presentation/transport only. Monetary economics are supplied by Python.
export const ASSUMPTION_FIELDS = ['target_margin','minimum_margin','risk_buffer','expected_utilization','stress_utilization',
  'infrastructure_jod','support_jod','operations_jod','processing_ratio','processing_fixed_jod','annual_discount',
  'annual_allowance_cycles','rounding_jod','usd_to_jod','fx_source','fx_version','max_rate_age_days','ladder_min_price_gap'];
export const COVERAGE = ['ai_credits','data_credits','ai_and_data_credits','internal_allocation','additional_external'];
export function newPolicy(existing) {
  const a = existing?.assumptions || {};
  return { ...Object.fromEntries(ASSUMPTION_FIELDS.map(k => [k, a[k] ?? ''])),
    feature_treatments: { ...(a.feature_treatments || {}) }, cost_binding_policy_id: a.cost_binding_policy_id || '',
    refresh_frequency: a.refresh_frequency || '', unlimited_monthly_usage: JSON.stringify(a.unlimited_monthly_usage || {}, null, 2),
    effective_from: new Date().toISOString(), reason: '' };
}
export function policyPayload(form) {
  const a = Object.fromEntries(ASSUMPTION_FIELDS.filter(k => k !== 'ladder_min_price_gap' || form[k] !== '').map(k => [k, form[k]]));
  a.annual_allowance_cycles = Number(form.annual_allowance_cycles);
  a.max_rate_age_days = Number(form.max_rate_age_days);
  a.feature_treatments = form.feature_treatments;
  a.cost_binding_policy_id = form.cost_binding_policy_id || null;
  a.refresh_frequency = form.refresh_frequency || null;
  a.unlimited_monthly_usage = JSON.parse(form.unlimited_monthly_usage);
  return { assumptions: a, effective_from: form.effective_from, reason: form.reason };
}
export function analysisPayload(planKey, mode, limits, entitlements, refresh, policyId) {
  return { plan_key: planKey, ...(policyId ? { policy_id: policyId } : {}),
    ...(mode === 'simulate' ? { simulation: { limits: Object.fromEntries(Object.entries(limits).map(([k,v]) => [k, v === '' ? null : Number(v)])),
      entitlements, ...(refresh ? { refresh_frequency: refresh } : {}) } } : {}) };
}
