export const ONBOARDING_RETURN_PATH_KEY = 'keel.onboarding.returnPath';
const ALLOWED_RETURN_PATHS = new Set(['/dashboard', '/market']);

export function hasActivePlanAccess(subscription) {
  return Boolean(
    subscription?.assigned === true
      && subscription?.hasAccess === true
      && ['active', 'trialing'].includes(subscription?.billingStatus),
  );
}

export function hasCurrentTrialAccess(subscription) {
  return hasActivePlanAccess(subscription)
    && subscription.trialUsed === true
    && subscription.billingStatus === 'trialing'
    && Boolean(subscription.trialEndsAt);
}

export function canStartPlanTrial(subscription, plan) {
  if (!plan?.selfServe || !(plan.trialDays > 0) || subscription?.trialUsed
      || subscription?.assigned || subscription?.hasSubscription) return false;
  // Older API responses carry only the aggregate flag; current responses
  // identify each eligible plan and never rely on the default trial plan.
  return Array.isArray(subscription?.trialEligiblePlanIds)
    ? subscription.trialEligiblePlanIds.includes(plan.id)
    : subscription?.trialAvailable === true;
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
