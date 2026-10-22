import { useMutation, useQueryClient } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

// Takes a campaign id, or { campaignId, imageFormat, prompt, channel, attach }.
export function useGenerateCampaignImage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (arg) => (typeof arg === 'string'
      ? marketingApi.generateImage(arg)
      : marketingApi.generateImage(arg.campaignId, arg)),
    onSuccess: (_data, arg) => {
      const campaignId = typeof arg === 'string' ? arg : arg.campaignId;
      queryClient.invalidateQueries({ queryKey: ['marketing-campaign', campaignId] });
      queryClient.invalidateQueries({ queryKey: ['marketing-assets', campaignId] });
    },
  });
}
