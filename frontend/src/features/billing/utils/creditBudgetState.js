/**
 * Map the billing API's Credit summary to a truthful customer-facing state.
 * A missing/malformed budget is unknown; only zero means not included. Null
 * is the backend's explicit unlimited value.
 */
export function getCreditBudgetState(budget) {
  if (!budget || typeof budget !== 'object') return 'unknown';
  const { limit, consumed, reserved, remaining } = budget;
  if (!Number.isFinite(consumed) || consumed < 0 || !Number.isFinite(reserved) || reserved < 0) return 'unknown';
  if (limit !== null && (!Number.isFinite(limit) || limit < 0)) return 'unknown';
  if (limit === 0) return 'notIncluded';
  if (limit === null) return 'unlimited';
  if (!Number.isFinite(remaining) || remaining < 0) return 'unknown';
  if (consumed + reserved >= limit) return 'reached';
  if (budget.warning) return 'approaching';
  return 'normal';
}
