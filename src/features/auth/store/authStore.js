import { create } from 'zustand';
import {
  authSessionStorage,
  normalizeAuthSession,
} from './authSessionStorage.js';

export const AUTH_STATUS = Object.freeze({
  INITIALIZING: 'initializing',
  UNAUTHENTICATED: 'unauthenticated',
  AUTHENTICATED: 'authenticated',
});

const emptySessionState = {
  user: null,
  tenantId: null,
  roles: [],
  accessToken: null,
  refreshToken: null,
};

// Until a cookie-based backend contract exists, a bearer access token is the
// only reliable proof of an authenticated client session.
const isAuthenticatedSession = (session) => Boolean(session?.accessToken);

export const useAuthStore = create((set, get) => ({
  ...emptySessionState,
  status: AUTH_STATUS.INITIALIZING,
  isHydrated: false,

  initialize: () => {
    if (get().isHydrated) return;
    const session = authSessionStorage.read();

    set({
      ...(session ?? emptySessionState),
      status: isAuthenticatedSession(session)
        ? AUTH_STATUS.AUTHENTICATED
        : AUTH_STATUS.UNAUTHENTICATED,
      isHydrated: true,
    });
  },

  setSession: (session) => {
    const normalizedSession = normalizeAuthSession(session);
    authSessionStorage.write(normalizedSession);
    set({
      ...normalizedSession,
      status: isAuthenticatedSession(normalizedSession)
        ? AUTH_STATUS.AUTHENTICATED
        : AUTH_STATUS.UNAUTHENTICATED,
      isHydrated: true,
    });
  },

  clearSession: () => {
    authSessionStorage.clear();
    set({
      ...emptySessionState,
      status: AUTH_STATUS.UNAUTHENTICATED,
      isHydrated: true,
    });
  },

  setUser: (user) => {
    const nextSession = normalizeAuthSession({ ...get(), user });
    if (isAuthenticatedSession(nextSession)) authSessionStorage.write(nextSession);
    else authSessionStorage.clear();
    set({
      ...nextSession,
      status: isAuthenticatedSession(nextSession)
        ? AUTH_STATUS.AUTHENTICATED
        : AUTH_STATUS.UNAUTHENTICATED,
    });
  },
}));

export const selectIsAuthenticated = (state) => state.status === AUTH_STATUS.AUTHENTICATED;
export const getAuthAccessToken = () => useAuthStore.getState().accessToken;
