import { queryClient } from '../../../shared/lib/queryClient.js';
import { useOnboardingStore } from '../../onboarding/store/onboardingStore.js';
import { clearPendingRegistration } from '../pendingRegistration.js';

export const identityKey = (session) => session?.accessToken
  ? JSON.stringify([session.user?.id ?? null, session.tenantId ?? null]) : null;

// Run synchronously before publishing another identity, including cross-tab
// adoption. Destroy old queries so late responses cannot repopulate this cache.
export function resetAccountState() {
  queryClient.clear();
  useOnboardingStore.getState().reset();
  clearPendingRegistration();
  try {
    for (const key of ['keel.onboarding.returnPath', 'keel.onboarding.checkoutPending']) {
      globalThis.sessionStorage?.removeItem(key);
    }
  } catch { /* Private mode: in-memory isolation still applies. */ }
}

export function resetForIdentityChange(previous, next) {
  if (identityKey(previous) !== identityKey(next)) resetAccountState();
}
