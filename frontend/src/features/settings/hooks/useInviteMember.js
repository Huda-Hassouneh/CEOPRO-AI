import { useMutation } from '@tanstack/react-query';
import { teamApi } from '../api/teamApi.js';

export function useInviteMember() {
  return useMutation({ mutationFn: teamApi.inviteMember });
}
