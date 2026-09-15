import { useQuery } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function useSubscription(companyId) {
  return useQuery({
    queryKey: ['subscription', companyId],
    queryFn: () => billingApi.getSubscription({ companyId }),
  });
}
