import { useQuery } from '@tanstack/react-query';
import { competitorsApi } from '../api/competitorsApi.js';

export function useCompetitorProfile(id) {
  return useQuery({
    queryKey: ['competitor-profile', id],
    queryFn: () => competitorsApi.profile(id),
    enabled: Boolean(id),
  });
}
