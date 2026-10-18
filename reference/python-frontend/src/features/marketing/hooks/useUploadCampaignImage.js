import { useMutation, useQueryClient } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

export function useUploadCampaignImage() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: marketingApi.uploadCampaignImage,
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['marketing-campaign', variables.campaignId] });
    },
  });
}
