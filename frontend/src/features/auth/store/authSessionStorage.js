const AUTH_SESSION_STORAGE_KEY = 'ceopro_auth_session';
const LEGACY_SESSION_KEY = 'ceopro_session';
const LEGACY_TOKEN_KEY = 'ceopro_token';

const getStorage = () => {
  if (typeof window === 'undefined') return null;

  try {
    return window.localStorage;
  } catch {
    return null;
  }
};

const safeParse = (value) => {
  if (!value) return null;

  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
};

export function normalizeAuthSession(session = {}) {
  const roleKey = session.roleKey ?? session.role ?? (Array.isArray(session.roles) ? session.roles[0] : null) ?? null;
  const roles = Array.isArray(session.roles)
    ? session.roles
    : roleKey
      ? [roleKey]
      : [];

  return {
    user: session.user ?? null,
    tenantId: session.tenantId ?? null,
    roleKey,
    // Kept as a compatibility view for existing tenant UI guards/settings.
    // Canonical authorization identity is roleKey from TenantUser.
    roles,
    accessToken: session.accessToken ?? null,
    refreshToken: session.refreshToken ?? null,
  };
}

export function persistAuthSession(session) {
  const storage = getStorage();
  if (!storage) return;

  try {
    storage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(normalizeAuthSession(session)));
    storage.removeItem(LEGACY_SESSION_KEY);
    storage.removeItem(LEGACY_TOKEN_KEY);
  } catch {
    // Keep the in-memory session usable when persistence is unavailable.
  }
}

export function clearPersistedAuthSession() {
  const storage = getStorage();
  if (!storage) return;

  try {
    storage.removeItem(AUTH_SESSION_STORAGE_KEY);
    storage.removeItem(LEGACY_SESSION_KEY);
    storage.removeItem(LEGACY_TOKEN_KEY);
  } catch {
    // Clearing the in-memory store remains authoritative for this session.
  }
}

export function readPersistedAuthSession() {
  const storage = getStorage();
  if (!storage) return null;

  try {
    const storedValue = storage.getItem(AUTH_SESSION_STORAGE_KEY);
    if (storedValue) {
      const storedSession = safeParse(storedValue);
      if (storedSession) return normalizeAuthSession(storedSession);
      storage.removeItem(AUTH_SESSION_STORAGE_KEY);
    }

    const legacySession = safeParse(storage.getItem(LEGACY_SESSION_KEY));
    const legacyAccessToken = storage.getItem(LEGACY_TOKEN_KEY);
    if (!legacySession && !legacyAccessToken) return null;

    const migratedSession = normalizeAuthSession({
      ...legacySession,
      accessToken: legacySession?.accessToken ?? legacyAccessToken ?? null,
      roleKey: legacySession?.roleKey ?? legacySession?.role ?? null,
      roles: legacySession?.roles ?? (legacySession?.role ? [legacySession.role] : []),
    });
    persistAuthSession(migratedSession);
    return migratedSession;
  } catch {
    return null;
  }
}

export const authSessionStorage = Object.freeze({
  key: AUTH_SESSION_STORAGE_KEY,
  read: readPersistedAuthSession,
  write: persistAuthSession,
  clear: clearPersistedAuthSession,
});
