import { useMutation, useQueryClient } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

export function useCreateCampaign() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: marketingApi.createCampaign,
    // A failed attempt is saved too (as "Failed"), so the list is refreshed either way.
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['marketing-campaigns'] });
    },
  });
}
