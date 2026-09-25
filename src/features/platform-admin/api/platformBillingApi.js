import httpClient from '../../../shared/lib/httpClient.js';

const base = '/platform-admin/billing';
const unwrap = request => request.then(response => response.data);

export const platformBillingApi = Object.freeze({
  getTenants: () => unwrap(httpClient.get(`${base}/tenants`)),
  getSubscriptions: () => unwrap(httpClient.get(`${base}/subscriptions`)),

  getPlans: () => unwrap(httpClient.get(`${base}/plans`)),
  createPlan: payload => unwrap(httpClient.post(`${base}/plans`, payload)),
  updatePlan: (planId, payload) => unwrap(httpClient.patch(`${base}/plans/${encodeURIComponent(planId)}`, payload)),

  getCustomPlans: () => unwrap(httpClient.get(`${base}/custom-plans`)),
  setCustomPlanActive: (planId, isActive) => unwrap(httpClient.patch(`${base}/custom-plans/${encodeURIComponent(planId)}/status`, { isActive })),

  getCustomPlanQuotes: () => unwrap(httpClient.get(`${base}/custom-quotes`)),
  getCustomPlanQuote: quoteId => unwrap(httpClient.get(`${base}/custom-quotes/${encodeURIComponent(quoteId)}`)),
  createCustomPlanQuote: payload => unwrap(httpClient.post(`${base}/custom-quotes`, payload)),
  updateCustomPlanQuote: (quoteId, payload) => unwrap(httpClient.patch(`${base}/custom-quotes/${encodeURIComponent(quoteId)}`, payload)),
  calculateCustomPlanQuote: quoteId => unwrap(httpClient.post(`${base}/custom-quotes/${encodeURIComponent(quoteId)}/calculate`)),
  approveCustomPlanQuote: (quoteId, payload) => unwrap(httpClient.post(`${base}/custom-quotes/${encodeURIComponent(quoteId)}/approve`, payload)),
  sendCustomPlanQuote: quoteId => unwrap(httpClient.post(`${base}/custom-quotes/${encodeURIComponent(quoteId)}/send`)),
  rejectCustomPlanQuote: quoteId => unwrap(httpClient.post(`${base}/custom-quotes/${encodeURIComponent(quoteId)}/reject`)),

  getCustomPlanPricingPolicy: () => unwrap(httpClient.get(`${base}/pricing-policy`)),
  updateCustomPlanPricingPolicy: payload => unwrap(httpClient.patch(`${base}/pricing-policy`, payload)),
  getVendorRates: () => unwrap(httpClient.get(`${base}/vendor-rates`)),
  createVendorRate: payload => unwrap(httpClient.post(`${base}/vendor-rates`, payload)),
  updateVendorRate: (rateId, payload) => unwrap(httpClient.patch(`${base}/vendor-rates/${encodeURIComponent(rateId)}`, payload)),

  getPromoCodes: () => unwrap(httpClient.get(`${base}/promo-codes`)),
  createPromoCode: payload => unwrap(httpClient.post(`${base}/promo-codes`, payload)),
  updatePromoCode: (promoCodeId, payload) => unwrap(httpClient.patch(`${base}/promo-codes/${encodeURIComponent(promoCodeId)}`, payload)),
  linkPromoCodeToPlan: ({ promoCodeId, planId }) => unwrap(httpClient.post(`${base}/promo-codes/${encodeURIComponent(promoCodeId)}/plans/${encodeURIComponent(planId)}`)),

  getFeatures: () => unwrap(httpClient.get(`${base}/features`)),
  getFeature: featureId => unwrap(httpClient.get(`${base}/features/${encodeURIComponent(featureId)}`)),
  createFeature: payload => unwrap(httpClient.post(`${base}/features`, payload)),
  updateFeature: (featureId, payload) => unwrap(httpClient.patch(`${base}/features/${encodeURIComponent(featureId)}`, payload)),
  getPlanFeatures: planId => unwrap(httpClient.get(`${base}/plans/${encodeURIComponent(planId)}/features`)),
  linkFeatureToPlan: (planId, payload) => unwrap(httpClient.post(`${base}/plans/${encodeURIComponent(planId)}/features`, payload)),
  updatePlanFeatureLimit: ({ planId, featureId, limitValue }) => unwrap(httpClient.patch(`${base}/plans/${encodeURIComponent(planId)}/features/${encodeURIComponent(featureId)}`, { limit_value: limitValue })),
});
