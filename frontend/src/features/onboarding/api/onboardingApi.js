import httpClient from '../../../shared/lib/httpClient.js';
export const onboardingApi = Object.freeze({
  getState: async () => (await httpClient.get('/onboarding/state')).data,
  saveStep: async (payload) => (await httpClient.put('/onboarding/state', payload)).data,
});
