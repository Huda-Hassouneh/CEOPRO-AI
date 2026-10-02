import httpClient from "../../../shared/lib/httpClient.js";

function unwrapResponse(response) {
  return response.data?.data ?? response.data;
}

export const marketIntelligenceApi = {
  getOverview: async ({ productId, periodDays } = {}) => {
    const response = await httpClient.get("/market-intelligence", {
      params: {
        productId: productId && productId !== "all" ? productId : undefined,
        periodDays
      }
    });

    return unwrapResponse(response);
  },

  generatePricingRecommendation: async (productId) => {
    if (!productId || productId === "all") {
      throw new Error(
        "A product ID is required to generate a pricing recommendation."
      );
    }

    const response = await httpClient.post(
      "/features/pricing/recommend",
      null,
      {
        params: {
          product_id: productId
        }
      }
    );

    return unwrapResponse(response);
  }
};
