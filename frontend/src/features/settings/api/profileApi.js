import httpClient from '../../../shared/lib/httpClient.js';

// The real backend endpoints - backend/src/ai/routers/settings.py's
// GET/PATCH /settings/profile. That endpoint only ever reads/writes
// full_name and preferred_language (email change and avatar upload are
// explicitly out of scope server-side per its own docstring - a bigger,
// separate flow) - jobTitle/avatarUrl stay undefined rather than
// fabricated, which ProfileForm.jsx already handles (it only renders the
// job title field when one is present, and Avatar already falls back to
// initials when avatarUrl is empty).
function toProfile(body) {
  return {
    id: body.user_id,
    fullName: body.full_name || '',
    email: body.email || '',
    jobTitle: undefined,
    avatarUrl: undefined,
  };
}

export const profileApi = {
  getProfile: async () => {
    const response = await httpClient.get('/settings/profile');
    return {
      profile: toProfile(response.data),
      // avatarUpload/emailChange stay false - genuinely unsupported
      // server-side, not merely unwired.
      capabilities: { updateProfile: true, avatarUpload: false, emailChange: false },
    };
  },

  updateProfile: async ({ fullName } = {}) => {
    const response = await httpClient.patch('/settings/profile', { full_name: fullName });
    return { persisted: true, profile: toProfile(response.data) };
  },
};
