import { useQuery } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function useSubscription(companyId, options = {}) {
  return useQuery({ queryKey: ['subscription', companyId], queryFn: billingApi.getSubscription, enabled: Boolean(companyId), ...options });
}
