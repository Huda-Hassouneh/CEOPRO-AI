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

test('pricingApi.recommendationHistory requests the tenant-scoped paginated backend history contract', async (t) => {
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    const url = new URL(req.url, 'http://localhost');
    assert.equal(req.method, 'GET');
    assert.equal(url.pathname, '/pricing/history/product%20one');
    assert.equal(url.searchParams.get('limit'), '10');
    assert.equal(url.searchParams.get('offset'), '20');
    res.end(JSON.stringify({
      items: [{ evidence_id: 'e1', recommendation_id: 'r1', generated_at: '2026-10-22T10:00:00+00:00',
        recommended_action: 'Hold price at 25 JOD', user_decision: 'PENDING', data_basis: 'INTERNAL_ONLY',
        confidence_score: 0.4, explanation: 'Supported by internal business data.' }],
      limit: 10, offset: 20, has_more: false,
    }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const result = await pricingApi.recommendationHistory('product one', { limit: 10, offset: 20 });
  assert.equal(result.items[0].data_basis, 'INTERNAL_ONLY');
  assert.equal(result.items[0].user_decision, 'PENDING');
  assert.equal(result.has_more, false);
});

// The comparison ladder endpoints (backend/src/ai/routers/pricing.py): a summary for a page of products, the full
// ladder for one, and a refresh that recomputes from stored competitor items.
test('pricingApi comparison calls send the right requests and unwrap the responses', async (t) => {
  const seen = [];
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    const url = new URL(req.url, 'http://localhost');
    seen.push(`${req.method} ${url.pathname}${url.search}`);
    if (url.pathname === '/pricing/comparisons' && req.method === 'GET') {
      return res.end(JSON.stringify({ products: { p1: { counts: { EXACT: 0, EQUIVALENT: 1, SIMILAR: 0, ADDED_VALUE: 0 }, headline: { tier: 'EQUIVALENT' } } } }));
    }
    if (url.pathname === '/pricing/comparisons/p%201' && req.method === 'GET') {
      return res.end(JSON.stringify({ product_id: 'p 1', covered: true, tiers: {} }));
    }
    if (url.pathname === '/pricing/comparisons/refresh' && req.method === 'POST') {
      return res.end(JSON.stringify({ competitors: 2, rows: 5 }));
    }
    res.statusCode = 404;
    res.end(JSON.stringify({ detail: 'not found' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const summary = await pricingApi.comparisons(['p1', 'p2']);
  assert.equal(summary.p1.headline.tier, 'EQUIVALENT');
  assert.ok(seen[0].includes('product_ids=p1%2Cp2') || seen[0].includes('product_ids=p1,p2'));

  const ladder = await pricingApi.ladder('p 1');
  assert.equal(ladder.covered, true);

  const refreshed = await pricingApi.refreshComparisons();
  assert.deepEqual(refreshed, { competitors: 2, rows: 5 });
});

test('pricingApi.setComparisonOverride PUTs the decision (null clears it) and returns the new ladder', async (t) => {
  const bodies = [];
  const server = http.createServer((req, res) => {
    let raw = '';
    req.on('data', (c) => { raw += c; });
    req.on('end', () => {
      res.setHeader('Content-Type', 'application/json');
      if (req.method === 'PUT' && req.url === '/pricing/comparisons/p1/override') {
        bodies.push(JSON.parse(raw));
        return res.end(JSON.stringify({ product_id: 'p1', covered: true }));
      }
      res.statusCode = 404;
      res.end('{}');
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const ladder = await pricingApi.setComparisonOverride('p1', { competitorId: 'c1', itemName: '30 min class', verdict: 'ADDITION' });
  assert.equal(ladder.covered, true);
  await pricingApi.setComparisonOverride('p1', { competitorId: 'c1', itemName: '30 min class' });
  assert.deepEqual(bodies, [
    { competitor_id: 'c1', item_name: '30 min class', verdict: 'ADDITION' },
    { competitor_id: 'c1', item_name: '30 min class', verdict: null },
  ]);
});
