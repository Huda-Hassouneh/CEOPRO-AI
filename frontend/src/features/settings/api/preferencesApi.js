import httpClient from '../../../shared/lib/httpClient.js';

// GET/PATCH /settings/notifications (backend/src/ai/routers/settings.py):
// which alert groups show in the app and go into the email summary, how
// often the summary is sent, and whether email can reach this person.
const toState = (data = {}) => ({
  preferences: data.notification_preferences,
  emailVerified: Boolean(data.email_verified),
  emailDeliveryAvailable: Boolean(data.email_delivery_available),
});

export const NOTIFICATION_GROUPS = ['stock', 'pricing', 'market', 'data', 'billing'];

export const preferencesApi = {
  getNotificationPreferences: async () => toState((await httpClient.get('/settings/notifications')).data),
  updateNotificationPreferences: async (patch = {}) => toState((await httpClient.patch('/settings/notifications', patch)).data),
};
