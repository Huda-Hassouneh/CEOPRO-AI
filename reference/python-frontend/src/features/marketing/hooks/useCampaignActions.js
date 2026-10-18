import { useMutation, useQueryClient } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

function useRefreshCampaigns() {
  const queryClient = useQueryClient();
  return (campaign) => {
    queryClient.invalidateQueries({ queryKey: ['marketing-campaigns'] });
    if (campaign?.campaign_id) queryClient.setQueryData(['marketing-campaign', campaign.campaign_id], campaign);
  };
}

export function useUpdateCampaign() {
  const refresh = useRefreshCampaigns();
  return useMutation({ mutationFn: ({ campaignId, ...edits }) => marketingApi.updateCampaign(campaignId, edits), onSuccess: refresh });
}

export function useDeleteCampaign() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (campaignId) => marketingApi.deleteCampaign(campaignId),
    onSuccess: (_data, campaignId) => {
      queryClient.removeQueries({ queryKey: ['marketing-campaign', campaignId] });
      queryClient.invalidateQueries({ queryKey: ['marketing-campaigns'] });
    },
  });
}
