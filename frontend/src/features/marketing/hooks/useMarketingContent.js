import { useQuery } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

export function useMarketingContent() {
  return useQuery({
    queryKey: ['marketing-content'],
    queryFn: marketingApi.listContent,
  });
}
