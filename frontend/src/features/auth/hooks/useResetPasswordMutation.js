import { useMutation } from '@tanstack/react-query';
import { authApi } from '../api/authApi.js';

export function useResetPasswordMutation(options = {}) {
  return useMutation({ mutationFn: authApi.resetPassword, ...options });
}
