import { useMutation } from '@tanstack/react-query';
import { authApi } from '../api/authApi.js';

export function useVerifyEmailMutation(options = {}) {
  return useMutation({ mutationFn: authApi.verifyEmail, ...options });
}
