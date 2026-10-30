export const fail = code => { throw Object.assign(new Error(code), { code }); };
export const validEmail = value => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value || '');
export function validatePlan(plan) {
  if (!plan.name?.en?.trim() || !plan.name?.ar?.trim() || !plan.description?.en?.trim() || !plan.description?.ar?.trim()) fail('invalid');
  if (plan.currency !== 'USD' || !['active', 'inactive'].includes(plan.status)) fail('invalid');
  if (plan.id !== 'custom' && (!Number.isFinite(plan.monthlyPrice) || plan.monthlyPrice < 0)) fail('invalid');
  if (!Number.isInteger(plan.trialDays) || plan.trialDays < 0 || plan.trialDays > 365) fail('invalid');
  if (!plan.billingOptions?.includes('monthly') || plan.billingOptions.some(v => !['monthly', 'three-months', 'six-months'].includes(v))) fail('invalid');
  for (const value of Object.values(plan.discounts || {})) if (!Number.isFinite(value) || value < 0 || value >= 100) fail('invalid');
  for (const [key, value] of Object.entries(plan.limits || {})) if (value !== null && (!Number.isFinite(value) || value < 0 || (key !== 'storageGb' && !Number.isInteger(value)))) fail('invalid');
  for (const value of Object.values(plan.entitlements || {})) if (![true, false, null].includes(value)) fail('invalid');
}
