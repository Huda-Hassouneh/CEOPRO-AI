import test from 'node:test';
import assert from 'node:assert/strict';
import { accountingRows, decimalText, emptyPrice, pricePayload, priceStatus } from '../src/features/platform/providerAccounting.js';
import { createPlatformBillingApi } from '../src/features/platform/platformBillingApi.js';

test('accounting distinguishes missing, zero and nonfinal prices and supplies missing RAG keys', () => {
  const rows = accountingRows([{ ...emptyPrice(), provider: 'brave_search', unit_cost_usd: '0.000000000001' }]);
  assert.equal(rows.length, 3);
  assert.equal(priceStatus(rows.find(row => row.provider === 'brave_search')), 'configured');
  assert.equal(priceStatus(rows[0]), 'missing');
  assert.equal(priceStatus({ unit_cost_usd: '0.0000', cost_is_final: false }), 'zero');
  assert.equal(priceStatus({ unit_cost_usd: '0.03', cost_is_final: false }), 'nonFinal');
  assert.equal(priceStatus({ unit_cost_usd: '0E-12', cost_is_final: true }), 'zero');
  assert.equal(decimalText('7.5000E-8'), '0.000000075000');
});
test('decimal strings survive the API with nullable policy margin and explicit zero', async () => {
  const form = { ...emptyPrice(), provider: 'brave_search', unit_cost_usd: '0.000123456789', source: 'invoice', reason: 'verified', verified_at: '2026-10-30' };
  const { body } = pricePayload(form);
  assert.equal(body.unit_cost_usd, form.unit_cost_usd);
  assert.equal(body.safety_margin, null);
  const calls = [];
  const api = createPlatformBillingApi({ get: async url => ({ data: { url } }), put: async (url, payload) => { calls.push([url, payload]); return { data: { schedules: [payload] } }; } });
  assert.equal((await api.providerAccounting()).url, '/platform/billing/provider-accounting');
  const result = await api.saveProviderAccounting(body);
  assert.deepEqual(calls, [['/platform/billing/provider-accounting', body]]);
  assert.equal(result.schedules[0].unit_cost_usd, form.unit_cost_usd);
});
test('invalid or missing prices/provenance never silently convert', () => {
  const valid = { ...emptyPrice(), provider: 'tavily', unit_cost_usd: '0', source: 'invoice', reason: 'approved', verified_at: '2026-10-30' };
  assert.equal(pricePayload(valid).body.unit_cost_usd, '0');
  for (const value of ['', '-1', 'NaN', 'Infinity', '1e-3', '0.0000000000001', '100000000', '1,23']) assert.ok(pricePayload({ ...valid, unit_cost_usd: value }).errors.unit_cost_usd);
  for (const field of ['provider', 'operation', 'source', 'reason', 'verified_at']) assert.ok(pricePayload({ ...valid, [field]: ' ' }).errors[field]);
  assert.ok(pricePayload({ ...valid, safety_margin: '2.1' }).errors.safety_margin);
});
