import { useQuery } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function useCustomPlanQuote(configuration) {
  return useQuery({
    queryKey: ['billing', 'custom-plan-preview-quote', configuration],
    queryFn: () => billingApi.getCustomPlanQuote(configuration),
  });
}
