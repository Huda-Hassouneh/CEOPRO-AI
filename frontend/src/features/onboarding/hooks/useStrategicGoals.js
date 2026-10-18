import { useMutation } from '@tanstack/react-query';
import { onboardingApi } from '../api/onboardingApi.js';

export function useStrategicGoals() {
  return useMutation({
    mutationFn: onboardingApi.saveGoals,
  });
}
