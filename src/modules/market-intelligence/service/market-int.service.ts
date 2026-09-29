import * as marketIntelligenceRepo from "../repo/market-int.repo.js";

export const getMarketIntelligence = async (
  tenantId: string,
  productId?: string,
  periodDays?: number
) => {
  const data = await marketIntelligenceRepo.getMarketIntelligence(
    tenantId,
    productId,
    periodDays
  );
  if (data) return data;
  return {
    companyId: tenantId,
    period: { days: periodDays ?? 30 },
    availablePeriods: [30, 90],
    products: [],
    selectedProduct: null,
    metrics: [],
    aiMarketIntelligence: null,
    expansionOpportunities: [],
    competitors: [],
    pricingRecommendations: [],
    recentPriceChanges: []
  };
};
