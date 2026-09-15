import { PREVIEW_CUSTOM_QUOTE, PREVIEW_PLANS } from '../config/billingPreviewData.js';
import { getPreviewSubscription } from '../config/subscriptionPreviewData.js';
import { planCatalogApi } from '../../../shared/catalog/planCatalog.js';

const previewDelay = (result) => new Promise((resolve) => {
  globalThis.setTimeout(() => resolve(result), 350);
});

export const billingApi = Object.freeze({
  getPlans: planCatalogApi.getPlans,
  getSubscription: async ({ companyId } = {}) => previewDelay(getPreviewSubscription(companyId)),
  getCustomPlanQuote: async (configuration) => ({ ...PREVIEW_CUSTOM_QUOTE, configuration }),
  createCheckout: async (payload) => previewDelay({
    ok: true,
    status: 'preview_succeeded',
    preview: true,
    realPaymentOccurred: false,
    payload,
  }),
  createUpgradeCheckout: async (payload) => previewDelay({
    available: false,
    success: false,
    realPaymentOccurred: false,
    payload,
  }),
  validateCoupon: async (payload) => ({ ok: true, preview: true, payload }),
  calculateTax: async (payload) => ({ ok: true, preview: true, amount: 0, payload }),
  paymentWebhookStatus: async () => ({ ok: true, preview: true, status: 'preview_succeeded' }),
});
