import { useMutation, useQueryClient } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

export function useCreateCampaign() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: marketingApi.createCampaign,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['marketing-campaigns'] });
    },
  });
}
