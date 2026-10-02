import { useMutation } from "@tanstack/react-query";
import { pricingApi } from "../api/pricingApi.js";

export function usePricingRecommendation() {
  return useMutation({
    mutationFn: (productId) => pricingApi.generateRecommendation(productId)
  });
}
