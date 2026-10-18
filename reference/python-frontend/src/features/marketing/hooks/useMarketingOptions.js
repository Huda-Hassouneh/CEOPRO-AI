import { useQuery } from '@tanstack/react-query';
import { marketingApi } from '../api/marketingApi.js';

export function useMarketingOptions() {
  return useQuery({
    queryKey: ['marketing-options'],
    queryFn: marketingApi.getOptions,
    staleTime: Infinity, // static reference data (strategies/themes), never changes mid-session
  });
}
