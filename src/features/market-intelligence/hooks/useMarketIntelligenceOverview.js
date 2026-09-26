import { useQuery } from "@tanstack/react-query";
import { marketIntelligenceApi } from "../api/marketIntelligenceApi.js";

export function useMarketIntelligenceOverview({ productId, periodDays }) {
  return useQuery({
    queryKey: ["market-intelligence-overview", productId, periodDays],
    queryFn: () => marketIntelligenceApi.getOverview({ productId, periodDays })
  });
}
