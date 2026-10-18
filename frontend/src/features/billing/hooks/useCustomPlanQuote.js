import { useQuery } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

/**
 * Fetches an already-created custom-plan quote by id.
 * Pricing is authoritative on the backend; this hook never calculates money.
 */
export function useCustomPlanQuote(quoteId) {
  return useQuery({
    queryKey: ['billing', 'custom-plan-quote', quoteId],
    queryFn: () => billingApi.getCustomPlanQuote(quoteId),
    enabled: Boolean(quoteId),
  });
}
