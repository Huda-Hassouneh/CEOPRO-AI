import { useMutation, useQueryClient } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

export function useRemoveBackground() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (campaignId) => marketingApi.removeBackground(campaignId),
    onSuccess: (_data, campaignId) => {
      queryClient.invalidateQueries({ queryKey: ['marketing-campaign', campaignId] });
    },
  });
}
