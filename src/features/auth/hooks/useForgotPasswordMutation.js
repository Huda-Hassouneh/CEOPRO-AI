import { useMutation } from '@tanstack/react-query';
import { authApi } from '../api/authApi.js';

export function useForgotPasswordMutation(options = {}) {
  return useMutation({ mutationFn: authApi.forgotPassword, ...options });
}
