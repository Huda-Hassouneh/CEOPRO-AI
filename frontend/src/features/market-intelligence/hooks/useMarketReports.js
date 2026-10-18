import { useQuery } from '@tanstack/react-query';
import { marketReportsApi } from '../api/marketReportsApi.js';

export function useMarketReports() {
  return useQuery({
    queryKey: ['market-reports'],
    queryFn: marketReportsApi.list,
  });
}
