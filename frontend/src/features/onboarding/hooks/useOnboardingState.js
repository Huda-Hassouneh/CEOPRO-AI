import { useQuery } from '@tanstack/react-query';
import { onboardingApi } from '../api/onboardingApi.js';

export function useOnboardingState() {
  return useQuery({
    queryKey: ['onboarding-state'],
    queryFn: onboardingApi.getState,
  });
}
