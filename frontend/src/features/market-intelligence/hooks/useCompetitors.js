import { useQuery } from '@tanstack/react-query';
import { competitorsApi } from '../api/competitorsApi.js';

export function useCompetitors() {
  return useQuery({
    queryKey: ['competitors'],
    queryFn: competitorsApi.list,
  });
}
