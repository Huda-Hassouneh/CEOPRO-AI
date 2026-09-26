import httpClient from "../../../shared/lib/httpClient.js";

export const competitorsApi = {
  list: async (companyId) => {
    const response = await httpClient.get(`/competitors`);
    return response.data?.data || response.data;
  },

  profile: async (companyId, competitorId) => {
    const response = await httpClient.get(`/competitors/${competitorId}`);
    return response.data?.data || response.data;
  },

  create: async (companyId, payload) => {
    const response = await httpClient.post(`/competitors`, payload);
    return response.data?.data || response.data;
  }
};
