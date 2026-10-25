import httpClient from '../../../shared/lib/httpClient.js';

const ROOT = '/billing/custom-offers';
const unwrap = (promise) => promise.then((response) => response.data);

// These methods mirror the Python customer contracts. Request bodies contain
// only configuration and idempotency data; price/entitlement terms stay server-owned.
export function createCustomOffersApi(client) {
  return Object.freeze({
    getConfigurator: () => unwrap(client.get(ROOT + '/configurator')),
    validateConfiguration: (payload) => unwrap(client.post(ROOT + '/configuration/validate', payload)),
    previewPricing: (payload) => unwrap(client.post(ROOT + '/pricing-preview', payload)),
    requestQuote: (payload) => unwrap(client.post(ROOT + '/quotes', payload)),
    listQuotes: (limit = 50) => unwrap(client.get(ROOT + '/quotes', { params: { limit } })),
    getQuote: (quoteId) => unwrap(client.get(ROOT + '/quotes/' + encodeURIComponent(quoteId))),
    acceptQuote: (quoteId, payload) => unwrap(client.post(ROOT + '/quotes/' + encodeURIComponent(quoteId) + '/accept', payload)),
    rejectQuote: (quoteId, payload) => unwrap(client.post(ROOT + '/quotes/' + encodeURIComponent(quoteId) + '/reject', payload)),
    createCheckoutAttempt: (quoteId, payload) => unwrap(client.post(ROOT + '/quotes/' + encodeURIComponent(quoteId) + '/checkout-attempts', payload)),
  });
}

export const customOffersApi = createCustomOffersApi(httpClient);

export function createIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return 'keel-' + Date.now() + '-' + Math.random().toString(36).slice(2);
}

export function buildCustomOfferConfiguration({ limits = {}, enabledFeatures = [], refreshFrequency = null }) {
  return {
    limits: Object.fromEntries(Object.entries(limits).map(([code, value]) => [code, Number(value)])),
    enabled_features: [...new Set(enabledFeatures)].sort(),
    refresh_frequency: refreshFrequency || null,
  };
}
