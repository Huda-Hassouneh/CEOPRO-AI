import { useQuery } from '@tanstack/react-query';
import { knowledgeBaseApi } from '../api/knowledgeBaseApi.js';

export function useKnowledgeDocuments(filters = {}) {
  return useQuery({
    queryKey: ['knowledge-documents', filters],
    queryFn: () => knowledgeBaseApi.listDocuments(filters),
  });
}
