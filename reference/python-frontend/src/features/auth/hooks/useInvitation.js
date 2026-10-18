import { useMutation, useQuery } from '@tanstack/react-query';
import { authApi } from '../api/authApi.js';
import { authQueryKeys } from '../api/authContracts.js';

export function useInvitationQuery(token, options = {}) {
  return useQuery({
    queryKey: authQueryKeys.invitation(token),
    queryFn: () => authApi.getInvitation(token),
    enabled: Boolean(token),
    ...options,
  });
}

export function useAcceptInvitationMutation(options = {}) {
  return useMutation({ mutationFn: authApi.acceptInvitation, ...options });
}
