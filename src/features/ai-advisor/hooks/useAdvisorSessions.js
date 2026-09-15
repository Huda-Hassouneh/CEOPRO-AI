import { useQuery } from '@tanstack/react-query';
import { advisorApi } from '../api/advisorApi.js';

export function useAdvisorSessions() {
  return useQuery({
    queryKey: ['advisor-sessions'],
    queryFn: advisorApi.listSessions,
  });
}
