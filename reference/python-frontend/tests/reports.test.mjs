import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { reportsApi } from '../src/features/reports/api/reportsApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

// reportsApi calls the real, mounted backend/src/ai/routers/reports.py
// (GET /reports/sales, GET /reports/financial-summary). What's worth a
// local test with no backend running: that the api layer sends the real
// request shape and maps the real response shape into what the UI
// consumes, same http.createServer technique as tests/pricing.test.mjs.
test('reportsApi.getSalesReport sends date range/limit as query params and returns the real response shape', async (t) => {
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/reports/sales' && req.method === 'GET') {
      assert.equal(url.searchParams.get('start_date'), '2026-01-01T00:00:00.000Z');
      assert.equal(url.searchParams.get('limit'), '50');
      return res.end(JSON.stringify({
        rows: [{ invoice_id: 'i1', product_name: 'Widget', quantity: 2, unit_price: 10, total_price: 20, has_cost_data: true, line_gross_profit: 8 }],
        returned_row_count: 1, total_row_count: 1, truncated: false,
      }));
    }
    res.statusCode = 404;
    res.end(JSON.stringify({ detail: 'not found' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const result = await reportsApi.getSalesReport({ startDate: '2026-01-01T00:00:00.000Z', limit: 50 });
  assert.equal(result.available, true);
  assert.equal(result.rows.length, 1);
  assert.equal(result.rows[0].line_gross_profit, 8);
});

test('reportsApi.getSalesReport returns available:false on a real request failure, never fabricated rows', async (t) => {
  const server = http.createServer((req, res) => {
    res.statusCode = 500;
    res.end(JSON.stringify({ detail: 'server error' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const result = await reportsApi.getSalesReport();
  assert.equal(result.available, false);
  assert.deepEqual(result.rows, []);
});

test('reportsApi.getFinancialSummary returns the real gross-profit shape, including a null gross profit when there is no cost data', async (t) => {
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    const url = new URL(req.url, 'http://localhost');
    if (url.pathname === '/reports/financial-summary' && req.method === 'GET') {
      assert.equal(url.searchParams.get('window_days'), '90');
      return res.end(JSON.stringify({
        revenue: { amount: 100, change_pct: null },
        gross_profit: { amount: null, change_pct: null },
        gross_margin_pct: { recent: null, change_pts: null },
        cost_data_coverage_pct: null,
      }));
    }
    res.statusCode = 404;
    res.end(JSON.stringify({ detail: 'not found' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const result = await reportsApi.getFinancialSummary({ windowDays: 90 });
  assert.equal(result.available, true);
  assert.equal(result.revenue.amount, 100);
  // Never turned into a fabricated 0 - the real "unknown" signal survives to the UI.
  assert.equal(result.gross_profit.amount, null);
});

test('reportsApi.getSalesReport asks the server for one page (limit/offset)', async (t) => {
  let seen;
  const server = http.createServer((req, res) => {
    seen = new URL(req.url, 'http://localhost').searchParams;
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ rows: [], returned_row_count: 0, total_row_count: 120, offset: 100, limit: 50 }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const result = await reportsApi.getSalesReport({ limit: 50, offset: 100 });
  assert.equal(seen.get('limit'), '50');
  assert.equal(seen.get('offset'), '100');
  assert.equal(result.total_row_count, 120);
});

test('reportsApi.exportSales downloads the whole period from the server as a file', async (t) => {
  let seen;
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    seen = { path: url.pathname, params: url.searchParams };
    res.setHeader('Content-Type', 'text/csv; charset=utf-8');
    res.end('\ufeffالتاريخ,الفاتورة\n2026-03-01,INV-1\n');
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const file = await reportsApi.exportSales({ format: 'csv', lang: 'ar', startDate: '2026-01-01T00:00:00.000Z' });
  assert.equal(seen.path, '/reports/sales/export');
  assert.equal(seen.params.get('format'), 'csv');
  assert.equal(seen.params.get('lang'), 'ar');
  assert.equal(seen.params.get('start_date'), '2026-01-01T00:00:00.000Z');
  assert.ok(file, 'a file was returned');
});

test('reportsApi.exportSales returns null when the export fails', async (t) => {
  const server = http.createServer((req, res) => { res.statusCode = 500; res.end(); });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  assert.equal(await reportsApi.exportSales({ format: 'json' }), null);
});
