import { useMutation } from '@tanstack/react-query';
import { knowledgeBaseApi } from '../api/knowledgeBaseApi.js';

export function useRagChat() {
  return useMutation({
    mutationFn: knowledgeBaseApi.chat,
  });
}
