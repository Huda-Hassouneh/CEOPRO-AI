import { useMutation } from '@tanstack/react-query';
import { billingApi } from '../api/customerBillingApi.js';

export function useCoupon() {
  return useMutation({
    mutationFn: billingApi.validateCoupon,
  });
}
