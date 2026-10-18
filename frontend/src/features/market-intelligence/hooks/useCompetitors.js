import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import { useQuery } from "@tanstack/react-query";
import { competitorsApi } from "../api/competitorsApi.js";
import { useAuthStore } from "../../auth/store/authStore.js";

export function useCompetitors(status = "active") {
  const companyId = useAuthStore((state) => state.tenantId);

  return useQuery({
    queryKey: ["competitors", companyId, status],
    queryFn: () => competitorsApi.list(companyId, status),
    enabled: UI_TESTING_MODE || Boolean(companyId)
  });
}
