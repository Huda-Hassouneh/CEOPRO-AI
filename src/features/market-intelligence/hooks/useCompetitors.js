import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import { useQuery } from "@tanstack/react-query";
import { competitorsApi } from "../api/competitorsApi.js";
import { useAuthStore } from "../../auth/store/authStore.js";

export function useCompetitors() {
  const companyId = useAuthStore((state) => state.tenantId);

  return useQuery({
    queryKey: ["competitors", companyId],
    queryFn: () => competitorsApi.list(companyId),
    enabled: UI_TESTING_MODE || Boolean(companyId)
  });
}
