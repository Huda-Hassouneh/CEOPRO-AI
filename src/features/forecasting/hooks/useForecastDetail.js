import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "../../auth/store/authStore.js";
import { forecastingApi } from "../api/forecastingApi.js";

export function useForecastDetail(id, periodDays = 30) {
  const tenantId = useAuthStore((state) => state.tenantId);

  return useQuery({
    queryKey: ["forecast-detail", tenantId, id, periodDays],
    queryFn: ({ signal }) =>
      forecastingApi.getForecastDetail(id, { periodDays, signal }),
    enabled: UI_TESTING_MODE || Boolean(tenantId && id),
    placeholderData: undefined
  });
}
