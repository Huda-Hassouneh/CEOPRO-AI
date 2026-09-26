import { useQuery } from "@tanstack/react-query";
import { competitorsApi } from "../api/competitorsApi.js";
import { useAuthStore } from "../../auth/store/authStore.js";

export function useCompetitorProfile(id) {
  const companyId = useAuthStore((state) => state.tenantId);

  return useQuery({
    queryKey: ["competitor-profile", companyId, id],
    queryFn: () => competitorsApi.profile(companyId, id),
    enabled: Boolean(companyId) && Boolean(id)
  });
}
