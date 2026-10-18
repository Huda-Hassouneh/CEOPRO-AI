import { useEffect, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "../../auth/store/authStore.js";
import { forecastingApi } from "../api/forecastingApi.js";

export function useForecastGeneration(productId, periodDays) {
  const tenantId = useAuthStore((state) => state.tenantId);
  const queryClient = useQueryClient();
  const scope = `${tenantId}:${productId}:${periodDays}`;
  const active = useRef(null);
  const mutation = useMutation({
    mutationKey: ["forecast-generation", tenantId, productId, periodDays],
    retry: false,
    mutationFn: async ({ scope: requestedScope, productId: id, periodDays: days, tenantId: tenant }) => {
      const controller = new AbortController();
      active.current = controller;
      try {
        const result = await forecastingApi.generateForecast(id, { periodDays: days, signal: controller.signal });
        // Mark inactive views stale, but refresh active query families in order
        // so one completed generation does not launch both read groups together.
        await queryClient.invalidateQueries({ queryKey: ["demand-prediction", tenant] });
        await queryClient.invalidateQueries({ queryKey: ["forecast-detail", tenant] });
        return { scope: requestedScope, result };
      } finally { if (active.current === controller) active.current = null; }
    }
  });
  useEffect(() => {
    mutation.reset();
    return () => { active.current?.abort(); };
  }, [scope]);
  return {
    isPending: mutation.isPending,
    data: mutation.data?.scope === scope ? mutation.data.result : null,
    error: mutation.variables?.scope === scope ? mutation.error : null,
    generate: () => {
      if (!tenantId || !productId || productId === "all" || active.current || mutation.isPending) return;
      mutation.mutate({ scope, productId, periodDays, tenantId });
    }
  };
}
