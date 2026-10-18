const previewResponse = (operation, payload = {}) => Promise.resolve({
  ok: true,
  operation,
  payload,
  preview: true,
});

export const onboardingApi = Object.freeze({
  getState: async () => ({ ok: true, preview: true, state: null }),
  saveProfile: (payload) => previewResponse('saveProfile', payload),
  saveRegionalPreferences: (payload) => previewResponse('saveRegionalPreferences', payload),
  saveGoals: (payload) => previewResponse('saveGoals', payload),
  connectSource: (payload) => previewResponse('connectSource', payload),
  complete: (payload) => previewResponse('completeOnboarding', payload),
});
