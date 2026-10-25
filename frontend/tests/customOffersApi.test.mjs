import test from 'node:test';
import assert from 'node:assert/strict';
import { buildCustomOfferConfiguration, createCustomOffersApi } from '../src/features/billing/api/customOffersApi.js';

function clientWith(responses = {}) {
  const calls = [];
  return { calls,
    get: async (url, config) => { calls.push({ method: 'GET', url, config }); return { data: responses[url] ?? {} }; },
    post: async (url, body) => { calls.push({ method: 'POST', url, body }); return { data: responses[url] ?? {} }; },
  };
}

test('Custom Plan configuration uses explicit Python fields and normalized integer limits', () => {
  assert.deepEqual(buildCustomOfferConfiguration({
    limits: { tracked_competitors: '4', data_credits: 120 },
    enabledFeatures: ['competitor_management', 'market_intelligence', 'competitor_management'],
    refreshFrequency: 'daily',
  }), {
    limits: { tracked_competitors: 4, data_credits: 120 },
    enabled_features: ['competitor_management', 'market_intelligence'],
    refresh_frequency: 'daily',
  });
});

test('configurator, validation and pricing preview use the actual read-only Python routes', async () => {
  const client = clientWith(); const api = createCustomOffersApi(client);
  const config = { limits: { tracked_products: 25 }, enabled_features: ['market_intelligence'], refresh_frequency: null };
  await api.getConfigurator(); await api.validateConfiguration(config); await api.previewPricing(config);
  assert.deepEqual(client.calls.map(({ method, url }) => [method, url]), [
    ['GET', '/billing/custom-offers/configurator'],
    ['POST', '/billing/custom-offers/configuration/validate'],
    ['POST', '/billing/custom-offers/pricing-preview'],
  ]);
  assert.deepEqual(client.calls[1].body, config);
});

test('durable request submits only configuration plus idempotency key and quote retrieval stays tenant API scoped', async () => {
  const client = clientWith({ '/billing/custom-offers/quotes': { quote_id: 'quote-id' } }); const api = createCustomOffersApi(client);
  const body = { limits: { tracked_products: 25 }, enabled_features: ['market_intelligence'], refresh_frequency: null, idempotency_key: 'retry-key' };
  const result = await api.requestQuote(body);
  assert.equal(result.quote_id, 'quote-id');
  assert.deepEqual(client.calls[0], { method: 'POST', url: '/billing/custom-offers/quotes', body });
  assert.equal('price' in client.calls[0].body, false);
  await api.listQuotes(25); await api.getQuote('quote / id');
  assert.deepEqual(client.calls[1], { method: 'GET', url: '/billing/custom-offers/quotes', config: { params: { limit: 25 } } });
  assert.equal(client.calls[2].url, '/billing/custom-offers/quotes/quote%20%2F%20id');
});

test('offer transitions require expected revision and idempotency; checkout requires a separate explicit call', async () => {
  const client = clientWith(); const api = createCustomOffersApi(client);
  const transition = { expected_revision: 2, idempotency_key: 'response-key' };
  await api.acceptQuote('q-1', transition); await api.rejectQuote('q-1', transition);
  assert.deepEqual(client.calls.map((call) => call.url), [
    '/billing/custom-offers/quotes/q-1/accept',
    '/billing/custom-offers/quotes/q-1/reject',
  ]);
  assert.deepEqual(client.calls[0].body, transition);
  assert.equal(client.calls.some((call) => call.url.endsWith('/checkout-attempts')), false);
});