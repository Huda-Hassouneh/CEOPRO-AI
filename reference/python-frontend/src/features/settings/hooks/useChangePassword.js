import { useMutation } from '@tanstack/react-query';
import { securityApi } from '../api/securityApi.js';

export function useChangePassword() {
  return useMutation({ mutationFn: securityApi.changePassword });
}
