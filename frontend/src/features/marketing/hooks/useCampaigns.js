import { useQuery } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

export function useCampaigns(params = {}) {
  return useQuery({
    queryKey: ['marketing-campaigns', params],
    queryFn: () => marketingApi.listCampaigns(params),
    placeholderData: (previous) => previous,
  });
}
