// The event is persisted by the verified payment authority, never by acceptance.
export const quoteHasVerifiedActivation = (quote) => Boolean(
  quote?.events?.some((event) => event.action === 'contract_activated'),
);

// These UI guards never change the subscription's existing access rights.
export function quoteIsExpired(quote, now = Date.now()) {
  return quote?.state === 'expired' || Boolean(
    ['submitted', 'approved', 'accepted'].includes(quote?.state)
      && quote?.valid_until && Date.parse(quote.valid_until) <= now,
  );
}
export function subscriptionBlocksCustomCheckout(subscription) {
  // hasSubscription already reflects the backend's current-subscription filter.
  return Boolean(subscription?.hasSubscription
    || (subscription?.assigned && subscription?.hasAccess && subscription.planId === 'custom'));
}
export function quoteFeatureLabel(t, code) {
  for (const prefix of ['billing.customPlan.featureNames.', 'billing.modules.']) {
    const key = prefix + code;
    const label = t(key);
    if (label && label !== key) return label;
  }
  return String(code).replaceAll('_', ' ');
}
