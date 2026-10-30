export const ONBOARDING_RETURN_PATH_KEY = 'keel.onboarding.returnPath';
const ALLOWED_RETURN_PATHS = new Set(['/dashboard', '/market']);

export function hasActivePlanAccess(subscription) {
  return Boolean(
    subscription?.assigned === true
      && subscription?.hasAccess === true
      && ['active', 'trialing'].includes(subscription?.billingStatus),
  );
}

export function getOnboardingReturnPath(storage = globalThis.sessionStorage) {
  const saved = storage?.getItem(ONBOARDING_RETURN_PATH_KEY);
  return ALLOWED_RETURN_PATHS.has(saved) ? saved : '/dashboard';
}

export function getPostSetupPath(subscription) {
  if (!subscription) return '/billing';
  if (hasActivePlanAccess(subscription)) return getOnboardingReturnPath();
  return subscription.hasSubscription ? '/billing' : '/onboarding/plan';
}
