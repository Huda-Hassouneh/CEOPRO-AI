import { useQuery } from '@tanstack/react-query';
import { advisorApi } from '../api/advisorApi.js';

export function useEvidenceTrail(sessionId) {
  return useQuery({
    queryKey: ['evidence-trail', sessionId],
    queryFn: () => advisorApi.evidenceTrail(sessionId),
    enabled: Boolean(sessionId),
  });
}
