import { useMutation } from '@tanstack/react-query';
import { authApi } from '../api/authApi.js';

export function useGoogleAuthMutation(options = {}) {
  return useMutation({ mutationFn: authApi.googleAuth, ...options });
}
