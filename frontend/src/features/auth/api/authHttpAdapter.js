import httpClient from '../../../shared/lib/httpClient.js';
import { authEndpoints } from './authContracts.js';

const unwrap = (request) => request.then((response) => response.data);

// The real backend (backend/src/ai/routers/auth.py) returns a flat,
// snake_case body - {access_token, tenant_id, user_id, role_key,
// business_name, full_name, preferred_language, ...} - consistent with
// every other endpoint in this API. The frontend's own internal session
// shape (authSessionStorage.js::normalizeAuthSession) is a separate,
// frontend-side convention ({user, tenantId, roles, accessToken,
// refreshToken}), not a backend contract - this is the one place that
// translates between the two, so neither side has to bend to the other's
// naming convention.
export function toSession(body) {
  if (!body?.access_token) return null;
  return {
    accessToken: body.access_token,
    refreshToken: null, // this backend issues a single bearer token, no refresh token yet
    tenantId: body.tenant_id ?? null,
    roles: body.role_key ? [body.role_key] : [],
    user: {
      id: body.user_id ?? null,
      email: body.email ?? null,
      fullName: body.full_name ?? null,
      preferredLanguage: body.preferred_language ?? null,
      businessName: body.business_name ?? null,
    },
  };
}

// SignupPage's local form state ({name, business, email, password,
// confirmPassword, acceptedTerms, country, currency}) never matched the
// backend's real SignupRequest ({email, password, full_name,
// business_name, country_code, primary_currency}) - this translated the
// form's own confirmPassword/acceptedTerms straight through as extra
// fields and never sent full_name/business_name/country_code/
// primary_currency at all, so every real signup 422'd server-side.
function toSignupRequest(payload) {
  return {
    email: payload.email,
    password: payload.password,
    full_name: payload.name,
    business_name: payload.business,
    country_code: payload.country,
    primary_currency: payload.currency,
  };
}

export const authHttpAdapter = Object.freeze({
  login: (payload) => unwrap(httpClient.post(authEndpoints.login, payload)).then((body) => ({ session: toSession(body) })),
  signup: (payload) => unwrap(httpClient.post(authEndpoints.signup, toSignupRequest(payload))).then((body) => ({ session: toSession(body), pendingRegistration: body.status === 'pending_verification' ? body : null })),
  forgotPassword: (payload) => unwrap(httpClient.post(authEndpoints.forgotPassword, payload)),
  verifyResetCode: (payload) => unwrap(httpClient.post(authEndpoints.verifyResetCode, payload)),
  resetPassword: (payload) => unwrap(httpClient.post(authEndpoints.resetPassword, payload)),
  resendVerification: (payload) => unwrap(httpClient.post(authEndpoints.resendVerification, payload)),
  verifyEmail: (payload) => unwrap(httpClient.post(authEndpoints.verifyEmail, payload)),
  getInvitation: (token) => unwrap(httpClient.get(`${authEndpoints.invitation}/${encodeURIComponent(token)}`)),
  acceptInvitation: ({ token, ...payload }) => unwrap(httpClient.post(`${authEndpoints.invitation}/${encodeURIComponent(token)}/accept`, payload)).then((body) => ({ session: toSession(body) })),
  logout: (payload) => unwrap(httpClient.post(authEndpoints.logout, payload)),
  // A fresh access token for the current, still-valid session.
  refresh: () => unwrap(httpClient.post(authEndpoints.refresh)).then((body) => body.access_token),
});
