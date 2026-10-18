import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import { useQuery } from "@tanstack/react-query";
import { useAuthStore } from "../../auth/store/authStore.js";
import { forecastingApi } from "../api/forecastingApi.js";

export function useDemandPrediction({ productId = "all", periodDays = 30 } = {}) {
  const tenantId = useAuthStore((state) => state.tenantId);

  return useQuery({
    queryKey: ["demand-prediction", tenantId, productId, periodDays],
    queryFn: ({ signal }) =>
      forecastingApi.predictDemand({ productId, periodDays, signal }),
    enabled: UI_TESTING_MODE || Boolean(tenantId),
    placeholderData: undefined
  });
}
