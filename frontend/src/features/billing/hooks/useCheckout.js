import { translateCurrent } from '../../../shared/lib/i18n.js';
import { useMutation } from '@tanstack/react-query';
import { billingApi } from '../api/billingApi.js';

export function useCheckout() {
  return useMutation({
    mutationFn: async ({ planId, billingPeriod, method = 'stripe', promoCode }) => {
      const payload = {
        planId,
        billing_period: billingPeriod,
        payment_method: method,
        ...(promoCode?.trim() ? { promoCode: promoCode.trim() } : {}),
      };

      const response = await billingApi.createCheckout(payload);
      const checkoutUrl = response?.data?.checkoutUrl;

      if (!checkoutUrl) {
        const error = new Error(translateCurrent("interfaceCopy.checkoutUrlMissing"));
        error.code = 'CHECKOUT_URL_MISSING';
        throw error;
      }

      window.location.assign(checkoutUrl);
      return { status: 'redirecting', data: response.data };
    },
  });
}
