import httpClient from '../../../shared/lib/httpClient.js';
import { billingApi as python } from './billingApi.js';
import { toOriginalPlan, toOriginalSubscription, toOriginalUsage, toOriginalInvoice } from './originalBillingModel.js';
export function getApiError(error) {
  const detail = error?.response?.data?.detail;
  return { status: error?.response?.status, code: detail?.reason || error?.code,
    message: detail?.message || (typeof detail === 'string' ? detail : error?.message) || 'Request failed.' };
}
const plans = async () => (await python.getPlans()).plans.map(toOriginalPlan);
export const billingApi = Object.freeze({
  cancelPendingCheckout: async () => (await httpClient.post('/billing/checkout/cancel-pending')).data,
  getPlans: async () => ({ data: await plans() }),
  getCustomPlans: async () => ({ data: [] }),
  getSubscription: async () => {
    const raw = await python.getSubscription();
    return { data: toOriginalSubscription(raw, await plans()), billing: raw };
  },
  getSubscriptionUsage: async () => toOriginalUsage(await python.getSubscription(), await plans()),
  getInvoices: async () => ({ data: (await python.getInvoices()).map(toOriginalInvoice) }),
  cancelSubscription: python.cancel, resumeSubscription: python.resume,
  cancelScheduledPlanChange: python.cancelScheduledChange, createSubscriptionRecovery: python.openPortal,
  createCheckout: async ({ planId, billing_period, promoCode }) => {
    const result = (await httpClient.post('/billing/checkout', {
      plan_key: planId, period_code: billing_period, ...(promoCode ? { promotion_code: promoCode } : {}),
    })).data;
    return { data: { checkoutUrl: result.url } };
  },
  changePlan: async ({ planId, billing_period }) => {
    const result = await python.changePlan({ planId, billingPeriod: billing_period });
    return { data: { ...result, state: result.state === 'payment_required' ? 'payment_action_required' : result.state,
      recoveryUrl: result.payment_url } };
  },
  previewChange: async ({ planId, billingPeriod }) => (await httpClient.post('/billing/change-plan/preview', {
    plan_key: planId, period_code: billingPeriod,
  })).data,
  validateCoupon: async ({ code, planId, billingPeriod }) => {
    const result = (await httpClient.post('/billing/promotions/validate', {
      code, plan_key: planId, period_code: billingPeriod,
    })).data;
    if (!result.valid) {
      const error = new Error('Promotion could not be applied.');
      error.code = result.reason || 'not_available';
      throw error;
    }
    return { data: { ...result.promotion, discountType: result.promotion?.discount_type === 'percent' ? 'percentage' : 'fixed',
      discountValue: result.promotion?.discount_value } };
  },
});
