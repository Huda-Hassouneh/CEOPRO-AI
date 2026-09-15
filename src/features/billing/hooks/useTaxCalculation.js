import { useMutation } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function useTaxCalculation() {
  return useMutation({
    mutationFn: billingApi.calculateTax,
  });
}
