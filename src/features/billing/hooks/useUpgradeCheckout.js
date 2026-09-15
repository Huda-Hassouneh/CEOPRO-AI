import { useMutation } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function useUpgradeCheckout() {
  return useMutation({ mutationFn: billingApi.createUpgradeCheckout });
}
