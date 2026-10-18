import { useMutation } from '@tanstack/react-query';
import { pricingApi } from '../api/pricingApi.js';

export function usePriceRecommendation() {
  return useMutation({
    mutationFn: pricingApi.recommend,
  });
}
