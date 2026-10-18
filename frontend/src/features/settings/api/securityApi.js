import httpClient from '../../../shared/lib/httpClient.js';

export const securityApi = {
  // The real backend endpoint - backend/src/ai/routers/settings.py's
  // POST /settings/security/change-password (real bcrypt verification of
  // the caller's current password before accepting a new one).
  changePassword: async ({ currentPassword, newPassword } = {}) => {
    await httpClient.post('/settings/security/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    });
    return { changed: true };
  },

  // GET /settings/security/sessions is real and does respond, but this
  // service issues stateless JWTs with no server-side session table (see
  // that endpoint's own docstring) - it always returns an empty list by
  // design, not "no sessions right now". available: false here matches
  // ActiveSessionsList.jsx's existing "session management is not
  // available" copy, which is the honest description of a service that
  // structurally cannot ever report session metadata - not the
  // "noSessionsTitle" copy, which would wrongly imply this could
  // transiently become non-empty.
  getSessions: async () => {
    await httpClient.get('/settings/security/sessions');
    return { sessions: [], available: false, canRevoke: false, canRevokeOthers: false };
  },

  // No MFA endpoint exists anywhere in the mounted backend - genuinely
  // unbuilt, not merely unwired.
  getMfa: async () => ({ available: false, mfa: null }),
};
