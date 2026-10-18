import { useQuery } from '@tanstack/react-query';
import { marketTrendsApi } from '../api/marketTrendsApi.js';

export function useMarketTrends() {
  return useQuery({
    queryKey: ['market-trends'],
    queryFn: marketTrendsApi.list,
  });
}
