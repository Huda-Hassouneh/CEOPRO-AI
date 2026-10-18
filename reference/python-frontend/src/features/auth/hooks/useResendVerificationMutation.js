import { useMutation } from '@tanstack/react-query';
import { authApi } from '../api/authApi.js';

export function useResendVerificationMutation(options = {}) {
  return useMutation({ mutationFn: authApi.resendVerification, ...options });
}
