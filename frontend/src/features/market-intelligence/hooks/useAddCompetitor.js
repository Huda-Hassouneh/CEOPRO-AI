import { useMutation, useQueryClient } from '@tanstack/react-query';
import { competitorsApi } from '../api/competitorsApi.js';
import { useAuthStore } from '../../auth/store/authStore.js';
export function useAddCompetitor() {
  const companyId = useAuthStore(state => state.tenantId);
  const cache = useQueryClient();
  return useMutation({ mutationFn: payload => competitorsApi.create(companyId, payload), onSuccess: async () => {
    await Promise.all([cache.invalidateQueries({ queryKey: ['competitors', companyId] }),cache.invalidateQueries({ queryKey: ['subscription','usage'] })]);
  } });
}
