import httpClient from '../../shared/lib/httpClient.js';
const unwrap = (promise) => promise.then((response) => response.data);
const enc = encodeURIComponent;
const root = '/platform/billing';
export function createPlatformBillingApi(client) {
  return Object.freeze({
    view: (name, limit = 100, offset = 0) => unwrap(client.get(`${root}/admin-views/${enc(name)}`, { params: { limit, offset } })),
    updatePlanStatus: (planKey, body) => unwrap(client.patch(`${root}/plans/${enc(planKey)}/status`, body)),
    updatePlanFeature: (planKey, body) => unwrap(client.patch(`${root}/plans/${enc(planKey)}/features`, body)),
    featureCatalog: () => unwrap(client.get(`${root}/feature-catalog`)),
    updateFeatureMetadata: (featureCode, body) => unwrap(client.patch(`${root}/feature-catalog/${enc(featureCode)}`, body)),
    companies: (limit = 100, offset = 0) => unwrap(client.get('/platform/companies', { params: { limit, offset } })),
    quotes: (state = '') => unwrap(client.get(`${root}/custom-quotes`, { params: { limit: 100, ...(state ? { state } : {}) } })),
    quote: (id) => unwrap(client.get(`${root}/custom-quotes/${enc(id)}`)),
    createQuote: (body) => unwrap(client.post(`${root}/custom-quotes`, body)),
    calculateQuote: (id) => unwrap(client.post(`${root}/custom-quotes/${enc(id)}/calculate`)),
    submitQuote: (id, body) => unwrap(client.post(`${root}/custom-quotes/${enc(id)}/submit`, body)),
    reviseQuote: (id, body) => unwrap(client.post(`${root}/custom-quotes/${enc(id)}/revisions`, body)),
    approveQuote: (id, body) => unwrap(client.post(`${root}/custom-quotes/${enc(id)}/approve`, body)),
    rejectQuote: (id, body) => unwrap(client.post(`${root}/custom-quotes/${enc(id)}/reject`, body)),
    policies: () => unwrap(client.get(`${root}/custom-plan-pricing/policies`)),
    createPolicy: (body) => unwrap(client.post(`${root}/custom-plan-pricing/policies`, body)),
    activatePolicy: (id, body) => unwrap(client.post(`${root}/custom-plan-pricing/policies/${enc(id)}/activate`, body)),
    rates: () => unwrap(client.get(`${root}/custom-plan-pricing/cost-rates`)),
    createRate: (body) => unwrap(client.post(`${root}/custom-plan-pricing/cost-rates`, body)),
    saveVendorRate: (body) => unwrap(client.post(`${root}/custom-plan-pricing/vendor-rates`, body)),
    infrastructureRates: () => unwrap(client.get(`${root}/custom-plan-pricing/infrastructure-rates`)),
    saveInfrastructureRate: (body) => unwrap(client.post(`${root}/custom-plan-pricing/infrastructure-rates`, body)),
    closeRate: (id, body) => unwrap(client.post(`${root}/custom-plan-pricing/cost-rates/${enc(id)}/close`, body)),
    bindings: (id) => unwrap(client.get(`${root}/custom-plan-pricing/policies/${enc(id)}/bindings`)),
    createBinding: (body) => unwrap(client.post(`${root}/custom-plan-pricing/bindings`, body)),
    assignContract: (body) => unwrap(client.post(`${root}/custom-contracts`, body)),
    promotions: () => unwrap(client.get(`${root}/promotions`)),
    createPromotionDraft: (body) => unwrap(client.post(`${root}/promotions`, body)),
    updatePromotionDraft: (id, body) => unwrap(client.patch(`${root}/promotions/${enc(id)}`, body)),
    activatePromotion: (id, body) => unwrap(client.post(`${root}/promotions/${enc(id)}/activate`, body)),
    disablePromotion: (id, reason) => unwrap(client.post(`${root}/promotions/${enc(id)}/disable`, { reason })),
  });
}
export const platformBillingApi = createPlatformBillingApi(httpClient);
