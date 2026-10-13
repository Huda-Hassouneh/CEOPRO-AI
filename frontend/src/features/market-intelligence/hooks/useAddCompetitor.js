import { useMutation, useQueryClient } from '@tanstack/react-query';
import { competitorsApi } from '../api/competitorsApi.js';

export function useAddCompetitor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: competitorsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['competitors'] });
      queryClient.invalidateQueries({ queryKey: ['competitor-landscape'] });
      queryClient.invalidateQueries({ queryKey: ['product-intelligence'] });
    },
  });
}
