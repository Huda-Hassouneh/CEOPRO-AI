import axios from 'axios';

let resolveAccessToken = () => null;
let handleUnauthorized = () => {};
let handleEmailVerificationRequired = () => {};

export function configureHttpClientAuth({ getAccessToken, onUnauthorized, onEmailVerificationRequired } = {}) {
  resolveAccessToken = typeof getAccessToken === 'function' ? getAccessToken : () => null;
  handleUnauthorized = typeof onUnauthorized === 'function' ? onUnauthorized : () => {};
  handleEmailVerificationRequired = typeof onEmailVerificationRequired === 'function' ? onEmailVerificationRequired : () => {};
}

export function unauthorizedBelongsToCurrentSession(requestAuthorization, currentToken) {
  return Boolean(currentToken && requestAuthorization === `Bearer ${currentToken}`);
}

// No `/api` prefix: the real FastAPI backend (backend/src/ai/main.py) mounts
// every router at the bare root (e.g. `/auth/login`, `/dashboard/metrics`,
// not `/api/auth/login`) - matching that here, rather than in every caller.
//
// `import.meta.env?.` (not `import.meta.env.`): Vite always injects `env`
// in the real app, but a plain `node some.test.mjs` run (this project's
// own tests/*.test.mjs convention, no Vite/Jest involved) imports this
// module outside Vite entirely - `import.meta.env` is then undefined, and
// a non-optional `.VITE_API_BASE_URL` access throws at import time,
// crashing every test that transitively imports any api/*.js module
// wired to httpClient. The optional chaining falls through to the same
// 'http://localhost:8000' default either way - no behavior change inside
// the real Vite-built app.
const httpClient = axios.create({
  baseURL: import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
});

// The interface language, so the API returns product and category names
// (and server-written messages) in the language the user is reading.
let resolveLanguage = () => null;

export function configureHttpClientLanguage(getLanguage) {
  resolveLanguage = typeof getLanguage === 'function' ? getLanguage : () => null;
}

httpClient.interceptors.request.use((config) => {
  const language = resolveLanguage();
  // A request that asks for a language of its own (e.g. a campaign written
  // in Arabic from the English screen) keeps it.
  if (language && !config.headers['X-App-Language']) {
    config.headers['X-App-Language'] = language;
  }
  const token = resolveAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Every protected endpoint's 401 means exactly one thing in this API (core/
// security.py's get_tenant_context(): missing/malformed/expired/invalid-
// signature Bearer token) - never a per-endpoint authorization distinction.
// Before this, a stale token (12h TTL, or a JWT_SECRET rotated on a backend
// redeploy) left the local session looking authenticated forever - every
// page kept calling the real API, kept getting 401, and showed its own
// generic "unavailable" error with a "Try again" button that only ever
// re-triggered the same 401, with nothing telling the user their session
// had actually expired. This clears the stale local session on any 401,
// which flips the auth store's isAuthenticated to false - ProtectedRoute
// (already mounted, subscribed to that same store) re-renders immediately
// and redirects to /login. Only the token that is active when the response
// arrives may be cleared; switching workspaces revokes the old token while
// old in-flight requests may still be returning.
httpClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const headers = error.config?.headers;
      const authorization = headers?.Authorization || headers?.authorization || null;
      handleUnauthorized(authorization);
    }
    // The API answers 403 with this reason until the email address is
    // confirmed (backend core/security.py); the app then shows the code screen.
    if (error.response?.status === 403 && error.response.headers?.['x-auth-reason'] === 'email-verification-required') {
      handleEmailVerificationRequired();
    }
    return Promise.reject(error);
  },
);

// Renewing the token before it expires is features/auth/sessionKeeper.js's job.
export default httpClient;
