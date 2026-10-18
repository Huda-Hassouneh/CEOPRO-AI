import { useMutation } from '@tanstack/react-query';
import { onboardingApi } from '../api/onboardingApi.js';

export function useBusinessProfile() {
  return useMutation({
    mutationFn: onboardingApi.saveProfile,
  });
}
