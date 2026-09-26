import { useQuery } from "@tanstack/react-query";
import { leaderboardApi } from "../api/leaderboardApi.js";
import { useAuthStore } from "../../auth/store/authStore.js";

export function useCompetitorLeaderboard() {
  const companyId = useAuthStore((state) => state.tenantId);

  return useQuery({
    queryKey: ["competitor-leaderboard", companyId],
    queryFn: () => leaderboardApi.getCompetitors(companyId),
    enabled: Boolean(companyId)
  });
}
