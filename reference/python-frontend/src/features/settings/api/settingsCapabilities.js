// backend/src/ai/routers/settings.py - every flag below now has a real,
// mounted endpoint behind it, except listInvitations (no GET endpoint
// exists to list pending invitations, only POST to create one).
export const settingsCapabilities = Object.freeze({
  updateProfile: true,
  updateCompany: true,
  listMembers: true,
  listInvitations: false,
  invite: true,
  changeRole: true,
  removeMember: true,
  changePassword: true,
});

export async function unsupportedSettingsAction() {
  const error = new Error('This settings action is not available.');
  error.code = 'SETTINGS_UNAVAILABLE';
  throw error;
}
