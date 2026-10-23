import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { demandApi } from '../src/features/forecasting/api/demandApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

test('demand API uses authenticated forecast, history, and overview contracts', async (t) => {
  const requests = [];
  const server = http.createServer((req, res) => {
    requests.push(`${req.method} ${req.url}`);
    res.setHeader('Content-Type', 'application/json');
    if (req.method === 'GET' && req.url === '/forecasting/overview?product_id=p%2F1') {
      return res.end(JSON.stringify({ products: [{ product_id: 'p/1', forecast_next_30: 18 }] }));
    }
    if (req.method === 'POST' && req.url === '/dashboard/products/p%2F1/forecast') {
      return res.end(JSON.stringify({ status: 'OK', forecast_id: 'f-1', reused: false }));
    }
    if (req.method === 'GET' && req.url === '/dashboard/products/p%2F1/forecast') {
      return res.end(JSON.stringify({ forecast_history: [{ predicted_demand: 18, confidence_score: 0.6 }] }));
    }
    res.statusCode = 404;
    return res.end(JSON.stringify({ detail: 'unexpected route' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const overview = await demandApi.overview({ productId: 'p/1' });
  const generated = await demandApi.generate('p/1');
  const history = await demandApi.history('p/1');

  assert.equal(overview.products[0].forecast_next_30, 18);
  assert.deepEqual(generated, { status: 'OK', forecast_id: 'f-1', reused: false });
  assert.equal(history.forecast_history[0].confidence_score, 0.6);
  assert.deepEqual(requests, [
    'GET /forecasting/overview?product_id=p%2F1',
    'POST /dashboard/products/p%2F1/forecast',
    'GET /dashboard/products/p%2F1/forecast',
  ]);
});
