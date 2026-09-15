import { useQuery } from '@tanstack/react-query';
import { ingestionApi } from '../api/ingestionApi.js';

export function useStagingReview() {
  return useQuery({
    queryKey: ['staging-review'],
    queryFn: ingestionApi.reviewStagingRows,
  });
}
