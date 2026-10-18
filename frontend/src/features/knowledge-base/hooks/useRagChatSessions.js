import { useQuery } from '@tanstack/react-query';
import { knowledgeBaseApi } from '../api/knowledgeBaseApi.js';

export function useRagChatSessions() {
  return useQuery({
    queryKey: ['rag-chat-sessions'],
    queryFn: knowledgeBaseApi.listSessions,
  });
}
