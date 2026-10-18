import httpClient from "../../../shared/lib/httpClient.js";

export const dashboardApi = {
  // Replaced mock adapter with actual backend call
  getAggregate: async ({ companyId, periodDays = 30 } = {}) => {
    // Note: If your backend relies on a tenant token/header instead of the URL,
    // you can change this to just apiClient.get('/dashboard')
    const response = await httpClient.get(`/companies/${companyId}/dashboard`, {
      params: {
        periodDays
      }
    });

    return response.data?.data ?? response.data;
  }
};
