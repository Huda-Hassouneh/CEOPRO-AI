import { useQuery } from '@tanstack/react-query';
import httpClient from '../../../shared/lib/httpClient.js';

// The same real GET /dashboard/market-overview endpoint (backend/src/ai/
// dashboard/market_overview.py) that marketIntelligenceApi.getOverview()
// also calls - shared here so Industry Trends doesn't duplicate the
// fetch/shape logic for the 3 real aggregates both pages show.
export function useMarketOverview() {
  return useQuery({
    queryKey: ['market-overview'],
    queryFn: async () => {
      const response = await httpClient.get('/dashboard/market-overview');
      return response.data;
    },
  });
}
