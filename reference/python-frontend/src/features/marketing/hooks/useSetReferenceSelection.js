import { useMutation, useQueryClient } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

export function useSetReferenceSelection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ campaignId, selection }) => marketingApi.setReferenceSelection(campaignId, selection),
    onSuccess: (_data, { campaignId }) => {
      queryClient.invalidateQueries({ queryKey: ['marketing-campaign', campaignId] });
    },
  });
}
