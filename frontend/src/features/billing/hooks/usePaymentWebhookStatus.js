import { useQuery } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function usePaymentWebhookStatus() {
  return useQuery({
    queryKey: ['payment-webhook-status'],
    queryFn: billingApi.paymentWebhookStatus,
  });
}
