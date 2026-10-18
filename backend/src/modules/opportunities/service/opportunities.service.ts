import * as leaderboardRepo from "../repo/opportunities.repo.js";

export const getCompetitorLeaderboard = async (tenantId: string) => {
  return await leaderboardRepo.getCompetitorLeaderboard(tenantId);
};
