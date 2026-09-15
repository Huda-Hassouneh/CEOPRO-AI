import { useMutation } from '@tanstack/react-query';
import { authApi } from '../api/authApi.js';

export function useLoginMutation(options = {}) {
  return useMutation({ mutationFn: authApi.login, ...options });
}
