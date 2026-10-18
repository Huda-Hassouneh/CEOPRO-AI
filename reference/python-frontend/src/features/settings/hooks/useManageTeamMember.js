import { useMutation, useQueryClient } from '@tanstack/react-query';
import { teamApi } from '../api/teamApi.js';

// PATCH/DELETE /settings/team/members/{id} - owner/admin only server-side,
// which also refuses to demote or remove the workspace's last owner.
export function useChangeMemberRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: teamApi.changeRole,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['team-members'] }),
  });
}

export function useRemoveMember() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: teamApi.removeMember,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['team-members'] }),
  });
}
