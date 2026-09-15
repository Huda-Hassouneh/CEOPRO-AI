import { useMutation } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function useCheckout() {
  return useMutation({
    mutationFn: billingApi.createCheckout,
  });
}
