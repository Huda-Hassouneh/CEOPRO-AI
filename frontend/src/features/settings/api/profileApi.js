import { unsupportedSettingsAction } from './settingsCapabilities.js';
const firstValue = (...values) => values.find((value) => typeof value === 'string' && value.trim()) || '';

export const profileApi = {
  getProfile: async ({ user } = {}) => ({
    profile: {
      id: user?.id || user?.userId || user?.user_id || null,
      fullName: firstValue(user?.full_name, user?.fullName, user?.displayName, user?.name, user?.profile?.fullName, user?.profile?.name),
      email: firstValue(user?.email, user?.emailAddress, user?.profile?.email),
      jobTitle: firstValue(user?.jobTitle, user?.position, user?.profile?.jobTitle, user?.profile?.position),
      avatarUrl: firstValue(user?.avatarUrl, user?.avatar, user?.picture, user?.profile?.avatarUrl),
    },
    capabilities: { updateProfile: false, avatarUpload: false, emailChange: false },
  }),
  updateProfile: unsupportedSettingsAction,
};
