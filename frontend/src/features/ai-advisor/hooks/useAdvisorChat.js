import { useMutation } from '@tanstack/react-query';
import { advisorApi } from '../api/advisorApi.js';

export function useAdvisorChat() {
  return useMutation({
    mutationFn: advisorApi.chat,
  });
}
