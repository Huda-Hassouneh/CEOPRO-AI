import { useMutation, useQueryClient } from '@tanstack/react-query';
import { sourceReviewApi } from '../api/sourceReviewApi.js';

export function useReviewSource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sourceId, termsPermit, reviewerReference }) =>
      sourceReviewApi.reviewSource(sourceId, { termsPermit, reviewerReference }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pending-sources'] });
      // Approving a source changes what's collected for its competitor -
      // existing overview/competitor views must refetch to reflect it.
      queryClient.invalidateQueries({ queryKey: ['competitors'] });
      queryClient.invalidateQueries({ queryKey: ['market-intelligence-overview'] });
    },
  });
}
