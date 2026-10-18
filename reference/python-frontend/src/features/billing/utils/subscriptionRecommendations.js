const CONTEXT_LIMIT_KEYS = Object.freeze({
  'product-limit': 'products',
  'rag-limit': 'aiCredits',
  'ai-credits': 'aiCredits',
  'data-credits': 'dataCredits',
  'report-limit': 'reports',
  'seat-limit': 'teamSeats',
  'storage-limit': 'storageGb',
});

export function getUsageState(used, limit) {
  if (Number.isFinite(used) && limit === null) return 'unlimited';
  if (limit === 0) return 'notIncluded';
  if (!Number.isFinite(used) || !Number.isFinite(limit) || limit <= 0) return 'unknown';
  if (used >= limit) return 'reached';
  if (used / limit >= 0.8) return 'approaching';
  return 'normal';
}

export function getUpgradeRecommendation(subscription, reason) {
  if (!subscription) return null;
  if (subscription.planId === 'custom') return null;
  if (subscription.status === 'trial') return { type: 'trial' };
  const supportedReasonKey = CONTEXT_LIMIT_KEYS[reason];
  if (supportedReasonKey && getUsageState(subscription.usage?.[supportedReasonKey], subscription.limits?.[supportedReasonKey]) === 'reached') {
    return { type: 'reached', key: supportedReasonKey, contextual: true };
  }
  const keys = Object.keys(subscription.limits || {}).filter((key) => subscription.usage?.[key] != null);
  const reached = keys.find((key) => getUsageState(subscription.usage[key], subscription.limits[key]) === 'reached');
  if (reached) return { type: 'reached', key: reached };
  const approaching = keys.find((key) => getUsageState(subscription.usage[key], subscription.limits[key]) === 'approaching');
  return approaching ? { type: 'approaching', key: approaching } : null;
}
