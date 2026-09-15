// Enable only after a verified service contract and authorization are integrated.
export const settingsCapabilities = Object.freeze({
  updateProfile: false,
  updateCompany: false,
  listMembers: false,
  listInvitations: false,
  invite: false,
  changeRole: false,
  removeMember: false,
  changePassword: false,
});

export async function unsupportedSettingsAction() {
  const error = new Error('This settings action is not available.');
  error.code = 'SETTINGS_UNAVAILABLE';
  throw error;
}
