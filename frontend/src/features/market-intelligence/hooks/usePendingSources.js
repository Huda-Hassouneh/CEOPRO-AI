import { useQuery } from '@tanstack/react-query';
import { sourceReviewApi } from '../api/sourceReviewApi.js';

export function usePendingSources(status) {
  return useQuery({
    queryKey: ['pending-sources', status],
    queryFn: () => sourceReviewApi.listSources({ status }),
  });
}
