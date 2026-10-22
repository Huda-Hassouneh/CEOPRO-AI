import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function useUsageHistory(enabled) {
  return useQuery({ queryKey: ['billing-usage-history'], queryFn: billingApi.getUsageHistory, enabled });
}

export function useInvoices(enabled) {
  return useQuery({ queryKey: ['billing-invoices'], queryFn: billingApi.getInvoices, enabled });
}

// Actions that leave the app (Checkout, the customer portal) redirect;
// the others refresh the subscription once the provider accepted them.
export function useBillingAction(action) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: billingApi[action],
    onSuccess: (result) => {
      if (result?.url) {
        // Only an https address is followed: the redirect target comes from the server response.
        if (/^https:\/\//i.test(result.url)) window.location.assign(result.url);
        return;
      }
      client.invalidateQueries({ queryKey: ['subscription'] });
    },
  });
}
