import {COMPETITOR_AI_ACTIONS_ENABLED} from '../config/competitorCapabilities.js';
import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import { useQuery } from "@tanstack/react-query";
import { competitorsApi } from "../api/competitorsApi.js";
import { useAuthStore } from "../../auth/store/authStore.js";

export function useCompetitorProfile(id) {
  const companyId = useAuthStore((state) => state.tenantId);

  return useQuery({
    queryKey: ["competitor-profile", companyId, id],
    queryFn: () => competitorsApi.profile(companyId, id),
    refetchInterval: COMPETITOR_AI_ACTIONS_ENABLED ? 5000 : false,
    enabled: (UI_TESTING_MODE || Boolean(companyId)) && Boolean(id)
  });
}
