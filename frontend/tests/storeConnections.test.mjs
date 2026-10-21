import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { dataConnectionsApi } from '../src/features/data-connections/api/dataConnectionsApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

test('WooCommerce and Shopify onboarding send the established provider contracts', async (t) => {
  const requests = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      requests.push({ method: req.method, url: req.url, body: body ? JSON.parse(body) : null });
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ source_id: 'synthetic-source', authorization_url: 'https://demo.myshopify.com/admin/oauth/authorize' }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  await dataConnectionsApi.connectWooCommerce({ url: ' https://shop.example.com ', consumerKey: ' ck_key ',
    consumerSecret: ' cs_secret ', frequency: 360 });
  await dataConnectionsApi.beginShopifyConnect({ url: ' demo.myshopify.com ', frequency: 60, includeTestOrders: true });
  await dataConnectionsApi.completeShopifyConnect('short-lived-ticket');

  assert.deepEqual(requests, [
    { method: 'POST', url: '/onboarding/connect/woocommerce', body: {
      url: 'https://shop.example.com', consumerKey: 'ck_key', consumerSecret: 'cs_secret',
      consent: true, syncFrequencyMinutes: 360,
    } },
    { method: 'POST', url: '/onboarding/connect/shopify/authorize', body: {
      url: 'demo.myshopify.com', consent: true, includeTestOrders: true, syncFrequencyMinutes: 60,
    } },
    { method: 'POST', url: '/onboarding/connect/shopify/complete', body: { ticket: 'short-lived-ticket' } },
  ]);
});
