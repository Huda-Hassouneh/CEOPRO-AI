import { useEffect } from "react";
import {
  useAuthStore,
  getAuthAccessToken
} from "../../features/auth/store/authStore.js";
import { configureHttpClientAuth } from "../../shared/lib/httpClient.js";

export function AuthProvider({ children }) {
  const initialize = useAuthStore((state) => state.initialize);

  useEffect(() => {
    configureHttpClientAuth({ getAccessToken: getAuthAccessToken });
    initialize();
  }, [initialize]);

  return children;
}

// Compatibility facade for existing consumers. State ownership remains Zustand.
export function useAuth() {
  const sessionState = useAuthStore();

  return {
    ...sessionState,
    session:
      sessionState.status === "authenticated"
        ? {
            user: sessionState.user,
            tenantId: sessionState.tenantId,
            roleKey: sessionState.roleKey,
            roles: sessionState.roles,
            accessToken: sessionState.accessToken,
            refreshToken: sessionState.refreshToken
          }
        : null
  };
}
