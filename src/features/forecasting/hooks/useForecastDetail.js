import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "../../auth/store/authStore.js";
import { forecastingApi } from "../api/forecastingApi.js";

export function useForecastDetail(id, periodDays = 30) {
  const tenantId = useAuthStore((state) => state.tenantId);

  return useQuery({
    queryKey: ["forecast-detail", tenantId, id, periodDays],
    queryFn: ({ signal }) =>
      forecastingApi.getForecastDetail(id, { periodDays, signal }),
    enabled: Boolean(tenantId && id),
    placeholderData: undefined
  });
}
