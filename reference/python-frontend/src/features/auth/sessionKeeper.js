// Keeps a signed-in session alive while someone is using the app.
//
// Access tokens are short-lived (backend JWT_EXPIRE_MINUTES). Shortly before
// the current one expires, if the user has interacted with the page since it
// was issued, it is swapped for a fresh one (POST /auth/refresh). A tab left
// untouched for a whole token lifetime is not renewed and signs out as
// before. The backend refuses renewal after SESSION_MAX_HOURS from sign-in.
//
// Open tabs share one session through localStorage: a tab adopts a newer
// token another tab saved instead of renewing on its own, and signs out when
// another tab signs out.

const RENEW_BEFORE_MS = 10 * 60 * 1000;
const CHECK_EVERY_MS = 30 * 1000;
const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'];

export function tokenClaims(token) {
  try {
    return JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return null;
  }
}

// The token says whether the email address is confirmed (ev) and whether
// confirmation was required when it was issued (evr).
export function needsEmailVerification(token) {
  const claims = token ? tokenClaims(token) : null;
  return Boolean(claims?.evr && claims.ev !== true);
}

export function tokenTimes(token) {
  try {
    const payload = tokenClaims(token);
    if (!payload?.exp) return null;
    const expiresAt = payload.exp * 1000;
    return { expiresAt, issuedAt: payload.iat ? payload.iat * 1000 : null };
  } catch {
    return null;
  }
}

// Pure decision, separate from timers and the DOM so it can be tested.
export function shouldRenew({ token, now, lastActivity }) {
  const times = token && tokenTimes(token);
  if (!times) return false;
  const remaining = times.expiresAt - now;
  if (remaining <= 0 || remaining > RENEW_BEFORE_MS) return false;
  // Active since this token was issued (older tokens have no issue time:
  // any activity in the last renewal window counts).
  const since = times.issuedAt ?? now - RENEW_BEFORE_MS;
  return lastActivity >= since;
}

export function startSessionKeeper({ getToken, renew, readStoredSession, adoptSession, storageKey }) {
  if (typeof window === 'undefined') return () => {};
  let lastActivity = Date.now();
  let renewing = false;
  const markActive = () => { lastActivity = Date.now(); };

  const check = async () => {
    const token = getToken();
    if (!token || renewing) return;
    // Another tab may already have renewed: use its token instead.
    const stored = readStoredSession();
    const storedTimes = stored?.accessToken && tokenTimes(stored.accessToken);
    const ownTimes = tokenTimes(token);
    if (storedTimes && ownTimes && stored.accessToken !== token && storedTimes.expiresAt > ownTimes.expiresAt) {
      adoptSession(stored);
      return;
    }
    if (!shouldRenew({ token, now: Date.now(), lastActivity })) return;
    renewing = true;
    try {
      await renew();
    } catch {
      // A refused renewal (sign-in too old, access removed) comes back as a
      // 401, which already signs the session out; anything else retries on
      // the next check.
    } finally {
      renewing = false;
    }
  };

  const onStorage = (event) => {
    if (event.key !== storageKey) return;
    adoptSession(readStoredSession());
  };
  const onVisible = () => { if (document.visibilityState === 'visible') check(); };

  ACTIVITY_EVENTS.forEach((name) => window.addEventListener(name, markActive, { passive: true, capture: true }));
  window.addEventListener('storage', onStorage);
  document.addEventListener('visibilitychange', onVisible);
  const timer = window.setInterval(check, CHECK_EVERY_MS);

  return () => {
    window.clearInterval(timer);
    ACTIVITY_EVENTS.forEach((name) => window.removeEventListener(name, markActive, { capture: true }));
    window.removeEventListener('storage', onStorage);
    document.removeEventListener('visibilitychange', onVisible);
  };
}
