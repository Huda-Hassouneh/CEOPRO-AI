import { useMutation } from '@tanstack/react-query';
import { authApi } from '../api/authApi.js';

export function useVerifyCodeMutation(options = {}) {
  return useMutation({ mutationFn: authApi.verifyResetCode, ...options });
}
