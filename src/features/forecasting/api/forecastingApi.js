import httpClient from "../../../shared/lib/httpClient";

// Tenant scope comes from the authenticated session. The backend derives the
// tenant from authentication rather than trusting a browser-supplied company ID.
export const forecastingApi = {
  predictDemand: async ({ productId = "all", periodDays = 30, signal } = {}) => {
    const response = await httpClient.get("/forecasting/demand", {
      params: { productId, periodDays },
      signal
    });
    return response.data?.data ?? response.data;
  },

  getForecastDetail: async (
    productId,
    { periodDays = 30, signal } = {}
  ) => {
    const response = await httpClient.get(
      `/forecasting/demand/${encodeURIComponent(productId)}`,
      { params: { periodDays }, signal }
    );
    return response.data?.data ?? response.data;
  },

  listForecasts: async (options = {}) =>
    forecastingApi.predictDemand(options),

  getRecommendations: async (options = {}) => {
    const data = await forecastingApi.predictDemand(options);
    return {
      ...data,
      forecasts: (data?.forecasts ?? []).filter(
        (row) => row.recommendedAction != null
      )
    };
  }
};
