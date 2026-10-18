import { useMutation } from '@tanstack/react-query';
import { onboardingApi } from '../api/onboardingApi.js';

export function useConnectDataSource() {
  return useMutation({
    mutationFn: onboardingApi.connectSource,
  });
}
