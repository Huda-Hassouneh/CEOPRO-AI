import { useMutation } from '@tanstack/react-query';
import { authApi } from '../api/authApi.js';

export function useSignupMutation(options = {}) {
  return useMutation({ mutationFn: authApi.signup, ...options });
}
