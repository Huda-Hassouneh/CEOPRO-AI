import { useMutation, useQueryClient } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

export function useGenerateCampaignImage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (campaignId) => marketingApi.generateImage(campaignId),
    onSuccess: (_data, campaignId) => {
      queryClient.invalidateQueries({ queryKey: ['marketing-campaign', campaignId] });
    },
  });
}
