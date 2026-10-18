import { translateCurrent } from '../../../shared/lib/i18n.js';
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
  const error = new Error(translateCurrent("interfaceCopy.settingUnavailable"));
  error.code = 'SETTINGS_UNAVAILABLE';
  throw error;
}
