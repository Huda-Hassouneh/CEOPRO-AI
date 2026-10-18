import httpClient from "../../../shared/lib/httpClient.js";

export const leaderboardApi = {
  getCompetitors: async (companyId) => {
    const response = await httpClient.get(`/leaderboard`);
    return response.data?.data || [];
  }
};
