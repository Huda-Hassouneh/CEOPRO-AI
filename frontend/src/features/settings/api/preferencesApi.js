import { unsupportedSettingsAction } from './settingsCapabilities.js';
export const preferencesApi = {
  getNotificationPreferences: async () => ({ preferences: [], channels: [], available: false }),
  updateNotificationPreferences: unsupportedSettingsAction,
};
