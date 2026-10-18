import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { productsApi } from '../src/features/products/api/productsApi.js';
import { quickSaleApi } from '../src/features/products/api/quickSaleApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

// api/*.js call the real, mounted backend/src/ai/routers/products.py and
// routers/sales.py endpoints (CRUD/RLS correctness of those endpoints
// themselves is covered by the backend's own pytest suite and this
// session's live curl/Playwright verification against a real Postgres +
// uvicorn instance, not re-tested here). What's worth a local test with
// no backend running: that each api function sends the request shape the
// real backend actually expects and returns what its component consumes.
// Same http.createServer technique as tests/settings.test.mjs.
test('products/quick-sale api layer sends the real request shape and returns what the UI consumes', async (t) => {
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      res.setHeader('Content-Type', 'application/json');
      const parsed = body ? JSON.parse(body) : null;
      if (req.url.startsWith('/products?') && req.method === 'GET') {
        return res.end(JSON.stringify({ products: [{ product_id: 'p1', product_name: 'Widget', current_price: 10, currency: 'JOD', stock_quantity: 5 }] }));
      }
      if (req.url === '/products' && req.method === 'POST') {
        assert.equal(parsed.current_price, 49.99);
        assert.equal(parsed.currency, 'JOD');
        return res.end(JSON.stringify({ product_id: 'p2', ...parsed }));
      }
      if (req.url === '/products/p1' && req.method === 'PATCH') {
        assert.deepEqual(parsed, { current_price: 39.99 });
        return res.end(JSON.stringify({ product_id: 'p1', current_price: 39.99 }));
      }
      if (req.url === '/products/p1' && req.method === 'DELETE') {
        res.statusCode = 204;
        return res.end();
      }
      if (req.url === '/sales/quick-sale' && req.method === 'POST' && parsed.unit_price !== undefined) {
        assert.deepEqual(parsed, { product_id: 'p1', quantity: 2, unit_price: 12 });
        return res.end(JSON.stringify({ invoice_id: 'i1', invoice_number: 'QS-ABC123', total_amount: 24, currency: 'JOD' }));
      }
      if (req.url === '/sales/quick-sale' && req.method === 'POST') {
        // unit_price omitted entirely when not overridden (backend defaults
        // to the product's own current_price) - never sent as null/undefined.
        assert.deepEqual(parsed, { product_id: 'p1', quantity: 1 });
        return res.end(JSON.stringify({ invoice_id: 'i2', invoice_number: 'QS-DEF456', total_amount: 10, currency: 'JOD' }));
      }
      res.statusCode = 404;
      res.end(JSON.stringify({ detail: 'not found' }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const list = await productsApi.list({ search: 'widget' });
  assert.equal(list.products[0].product_name, 'Widget');

  const created = await productsApi.create({ current_price: 49.99, currency: 'JOD' });
  assert.equal(created.ok, true);
  assert.equal(created.product.product_id, 'p2');

  const updated = await productsApi.update({ id: 'p1', current_price: 39.99 });
  assert.equal(updated.product.current_price, 39.99);

  const removed = await productsApi.remove('p1');
  assert.equal(removed.ok, true);
  assert.equal(removed.id, 'p1');

  const saleWithOverride = await quickSaleApi.sale({ productId: 'p1', quantity: 2, unitPrice: 12 });
  assert.equal(saleWithOverride.ok, true);
  assert.equal(saleWithOverride.sale.invoice_number, 'QS-ABC123');

  const saleAtListPrice = await quickSaleApi.sale({ productId: 'p1', quantity: 1 });
  assert.equal(saleAtListPrice.sale.invoice_number, 'QS-DEF456');
});
