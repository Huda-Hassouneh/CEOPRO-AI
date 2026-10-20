import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { pricingApi } from '../src/features/pricing/api/pricingApi.js';
import { reportCsv } from '../src/features/pricing/lib/reportCsv.js';
import httpClient from '../src/shared/lib/httpClient.js';

test('premium band and report calls send the right requests', async (t) => {
  const seen = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      const url = new URL(req.url, 'http://localhost');
      seen.push(`${req.method} ${url.pathname}${url.search} ${body}`);
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ products: [], categories: [] }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  await pricingApi.premiumBands();
  await pricingApi.setPremiumBand({ category: 'burgers', bandPct: 40 });
  await pricingApi.setPremiumBand({ category: undefined, bandPct: null });
  await pricingApi.comparisonReport(25);
  assert.deepEqual(seen, [
    'GET /pricing/premium-bands ',
    'PUT /pricing/premium-bands {"category":"burgers","band_pct":40}',
    'PUT /pricing/premium-bands {"category":null,"band_pct":null}',
    'GET /reports/price-comparison?limit=25 ',
  ]);
});

test('the report CSV has one row per product and neutralises formulas in names', () => {
  const tier = (count) => ({ count });
  const csv = reportCsv([{
    name: '=HYPERLINK("x")', currency: 'JOD', your_price: 4, headline: { tier: 'ADDED_VALUE', position_pct: null },
    tiers: { EXACT: tier(0), EQUIVALENT: tier(0), SIMILAR: tier(1), ADDED_VALUE: tier(2) },
    added_value_guidance: { range_low: 3.06, range_high: 4.8, band_pct: 60, band_source: 'owner' },
  }]);
  const lines = csv.split('\n');
  assert.equal(lines.length, 2);
  assert.ok(lines[0].startsWith('"product","currency"'));
  assert.ok(lines[1].startsWith('"\'=HYPERLINK(""x"")","JOD","4","ADDED_VALUE","0","0","1","2"'));
  assert.ok(lines[1].endsWith('"3.06","4.8","60","owner"'));
});
