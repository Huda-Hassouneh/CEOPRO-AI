import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import { useQuery } from "@tanstack/react-query";
import { leaderboardApi } from "../api/leaderboardApi.js";
import { useAuthStore } from "../../auth/store/authStore.js";

export function useCompetitorLeaderboard() {
  const companyId = useAuthStore((state) => state.tenantId);

  return useQuery({
    queryKey: ["competitor-leaderboard", companyId],
    queryFn: () => leaderboardApi.getCompetitors(companyId),
    enabled: UI_TESTING_MODE || Boolean(companyId)
  });
}
