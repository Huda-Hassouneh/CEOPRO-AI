import httpClient from "../../../shared/lib/httpClient";

export const forecastingApi = {
  // GET /companies/:companyId/forecasting/list
  listForecasts: async (companyId) => {
    const response = await httpClient.get(
      `/companies/${companyId}/forecasting/list`
    );
    return response.data?.data ?? response.data;
  },

  // GET /companies/:companyId/forecasting/demand/:productId
  getForecastDetail: async (productId) => {
    console.log({ productId });

    const response = await httpClient.get(`/forecasting/demand/${productId}`);
    console.log({ data: response.data?.data });

    return response.data?.data ?? response.data;
  },

  // GET /companies/:companyId/forecasting/demand?productId=&periodDays=
  predictDemand: async ({
    companyId,
    productId = "all",
    periodDays = 30
  } = {}) => {
    const response = await httpClient.get(`/forecasting/demand`, {
      params: { productId, periodDays }
    });

    return response.data?.data ?? response.data;
  },

  // GET /companies/:companyId/forecasting/recommendations
  getRecommendations: async (companyId) => {
    const response = await httpClient.get(`/forecasting/recommendations`);
    return response.data?.data ?? response.data;
  },

  // GET /companies/:companyId/forecasting/accuracy
  getModelAccuracy: async (companyId) => {
    const response = await httpClient.get(`/forecasting/accuracy`);
    return response.data?.data ?? response.data;
  },

  // No backend export endpoint currently exists.
  requestTablePdf: async () => ({ available: false })
};
