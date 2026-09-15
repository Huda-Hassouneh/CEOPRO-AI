import { PREVIEW_BILLING_CURRENCY, PREVIEW_PLANS } from './billingPreviewData.js';

const PREVIEW_SUBSCRIPTION = Object.freeze({
  planId: 'standard',
  status: 'active',
  billingPeriod: 'monthly',
  currency: PREVIEW_BILLING_CURRENCY,
  trialEndsAt: null,
  renewsAt: null,
  renewalStatus: null,
  usage: Object.freeze({
    products: 72,
    competitors: 5,
    ragQueries: 142,
    reports: 8,
    storageGb: 3.7,
  }),
});

// Centralized development-only account state. Plan prices and limits continue
// to come from billingPreviewData so onboarding and in-app billing cannot drift.
export function getPreviewSubscription(companyId) {
  const plan = PREVIEW_PLANS[PREVIEW_SUBSCRIPTION.planId];
  return {
    ...PREVIEW_SUBSCRIPTION,
    companyId: companyId || null,
    limits: plan?.limits || {},
    preview: true,
    available: true,
  };
}
