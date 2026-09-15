import { useQuery } from '@tanstack/react-query';
import { marketIntelligenceApi } from '../api/marketIntelligenceApi.js';

export function useMarketIntelligenceOverview({ companyId, productId, periodDays }) {
  return useQuery({
    queryKey: ['market-intelligence-overview', companyId, productId, periodDays],
    queryFn: () => marketIntelligenceApi.getOverview({ companyId, productId, periodDays }),
  });
}
