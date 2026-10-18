import { useQuery } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function useSubscription() {
  return useQuery({
    queryKey: ['subscription', 'current'],
    queryFn: billingApi.getSubscription,
    retry: false,
  });
}
