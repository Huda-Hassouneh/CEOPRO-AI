import * as leaderboardRepo from "./repo.js";

export const getCompetitorLeaderboard = async (tenantId: string) => {
  return await leaderboardRepo.getCompetitorLeaderboard(tenantId);
};
