import { useQuery } from '@tanstack/react-query';
import { teamApi } from '../api/teamApi.js';

export function useTeamMembers(context) {
  return useQuery({ queryKey: ['team-members', context], queryFn: () => teamApi.listMembers(context) });
}
