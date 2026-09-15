import { unsupportedSettingsAction } from './settingsCapabilities.js';
export const securityApi = {
  getSessions: async () => ({ sessions: [], available: false, canRevoke: false, canRevokeOthers: false }),
  changePassword: unsupportedSettingsAction,
  getMfa: async () => ({ available: false, mfa: null }),
};
