import httpClient from "../../../shared/lib/httpClient.js";

export const pricingApi = {
  generateRecommendation: async (productId) => {
    if (!productId || productId === "all") {
      throw new Error("A product ID is required.");
    }

    const response = await httpClient.post(
      "/features/pricing/recommend",
      {},
      {
        params: {
          product_id: productId
        }
      }
    );

    return response.data?.data ?? response.data;
  }
};
