import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { pricingApi } from '../src/features/pricing/api/pricingApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

// pricingApi.recommend() calls the real, mounted
// backend/src/ai/routers/pricing.py POST /pricing/recommend, which takes
// product_id as a query param (not a JSON body) - matching that
// endpoint's own real signature exactly.
test('pricingApi.recommend sends product_id as a query param and returns the real response shape', async (t) => {
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/pricing/recommend' && req.method === 'POST') {
      assert.equal(url.searchParams.get('product_id'), 'p1');
      return res.end(JSON.stringify({
        status: 'OK', action: 'lower', current_price: 30.0, suggested_price: 25.5,
        guardrail_clamped: false, margin_guardrail_clamped: null, matched_competitor_count: 2,
        confidence_score: 0.7, explanation: 'Real explanation text.', evidence_id: 'e1', outcome_id: 'o1',
      }));
    }
    res.statusCode = 404;
    res.end(JSON.stringify({ detail: 'not found' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const result = await pricingApi.recommend('p1');
  assert.equal(result.status, 'OK');
  assert.equal(result.action, 'lower');
  assert.equal(result.suggested_price, 25.5);
  assert.equal(result.explanation, 'Real explanation text.');
});
