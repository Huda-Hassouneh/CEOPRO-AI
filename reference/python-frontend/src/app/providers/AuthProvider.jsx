import { useEffect } from 'react';
import { useAuthStore, getAuthAccessToken } from '../../features/auth/store/authStore.js';
import { authSessionStorage } from '../../features/auth/store/authSessionStorage.js';
import { authHttpAdapter } from '../../features/auth/api/authHttpAdapter.js';
import { startSessionKeeper } from '../../features/auth/sessionKeeper.js';
import { configureHttpClientAuth } from '../../shared/lib/httpClient.js';

export function AuthProvider({ children }) {
  const initialize = useAuthStore((state) => state.initialize);
  const clearSession = useAuthStore((state) => state.clearSession);

  useEffect(() => {
    // onUnauthorized: any 401 means this session's token is no longer
    // valid server-side (expired, or a backend JWT_SECRET rotation) -
    // clearing it here (not on a specific page) fixes every protected
    // page at once, not just the dashboard. See httpClient.js's own
    // comment on the interceptor for the full reasoning.
    configureHttpClientAuth({
      getAccessToken: getAuthAccessToken,
      onUnauthorized: clearSession,
      onEmailVerificationRequired: () => useAuthStore.getState().setEmailVerificationBlocked(true),
    });
    initialize();
  }, [initialize, clearSession]);

  // Renew the access token while the app is in use (features/auth/sessionKeeper.js).
  useEffect(() => startSessionKeeper({
    getToken: getAuthAccessToken,
    renew: async () => useAuthStore.getState().setAccessToken(await authHttpAdapter.refresh()),
    readStoredSession: authSessionStorage.read,
    adoptSession: (session) => useAuthStore.getState().adoptSession(session),
    storageKey: authSessionStorage.key,
  }), []);

  return children;
}

// Compatibility facade for existing consumers. State ownership remains Zustand.
export function useAuth() {
  const sessionState = useAuthStore();
  return {
    ...sessionState,
    session: sessionState.status === 'authenticated'
      ? {
          user: sessionState.user,
          tenantId: sessionState.tenantId,
          roles: sessionState.roles,
          accessToken: sessionState.accessToken,
          refreshToken: sessionState.refreshToken,
        }
      : null,
  };
}
