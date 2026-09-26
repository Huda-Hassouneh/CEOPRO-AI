import httpClient from "../../../shared/lib/httpClient.js";

export const marketIntelligenceApi = {
  // Replaces the mock with a live call to your new Express route
  getOverview: async (params = { periodDays, productId }) => {
    const { productId, periodDays } = params;
    console.log({ periodDays, productId });
    // Uses axios/httpClient params to build ?productId=xyz&periodDays=30
    const response = await httpClient.get(`/market-intelligence`, {
      params: {
        productId: productId !== "all" ? productId : undefined,
        periodDays
      }
    });

    // Unwrap the nested Express response to pass clean data to React Query
    return response.data?.data || response.data;
  },

  // Future: POST /companies/:companyId/market-intelligence/exports
  requestPdfExport: async () => ({ available: false })
};
