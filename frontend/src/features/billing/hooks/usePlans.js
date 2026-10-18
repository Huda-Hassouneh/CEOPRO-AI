import { useQuery } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function usePlans() {
  return useQuery({
    queryKey: ['plans'],
    queryFn: billingApi.getPlans,
  });
}
