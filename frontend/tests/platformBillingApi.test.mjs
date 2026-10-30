import test from 'node:test';
import assert from 'node:assert/strict';
import { createPlatformBillingApi } from '../src/features/platform/platformBillingApi.js';

test('Platform billing adapter uses the Python admin-view and quote contracts', async () => {
  const calls = [];
  const client = {
    get: async (url, config) => { calls.push(['get', url, config]); return { data: { items: [] } }; },
    post: async (url, body) => { calls.push(['post', url, body]); return { data: { ok: true } }; },
  };
  const api = createPlatformBillingApi(client);
  await api.view('subscriptions', 25, 50);
  await api.quotes('submitted');
  await api.quote('quote/a');
  await api.calculateQuote('quote-id');
  await api.approveQuote('quote-id', { expected_revision: 2, idempotency_key: 'key', approval_reference: 'owner-ref' });
  await api.rejectQuote('quote-id', { expected_revision: 2, idempotency_key: 'key-2' });

  assert.deepEqual(calls, [
    ['get', '/platform/billing/admin-views/subscriptions', { params: { limit: 25, offset: 50 } }],
    ['get', '/platform/billing/custom-quotes', { params: { limit: 100, state: 'submitted' } }],
    ['get', '/platform/billing/custom-quotes/quote%2Fa', undefined],
    ['post', '/platform/billing/custom-quotes/quote-id/calculate', undefined],
    ['post', '/platform/billing/custom-quotes/quote-id/approve', { expected_revision: 2, idempotency_key: 'key', approval_reference: 'owner-ref' }],
    ['post', '/platform/billing/custom-quotes/quote-id/reject', { expected_revision: 2, idempotency_key: 'key-2' }],
  ]);
});

test('Platform billing adapter calls the Python pricing policy and verified rate contracts', async () => {
  const calls = [];
  const client = {
    get: async (url) => { calls.push(['get', url]); return { data: {} }; },
    post: async (url, body) => { calls.push(['post', url, body]); return { data: {} }; },
  };
  const api = createPlatformBillingApi(client);
  await api.policies();
  await api.createPolicy({ target_gross_margin: 0.4 });
  await api.activatePolicy('policy-id', { approval_evidence: 'evidence' });
  await api.rates();
  await api.createRate({ provider: 'synthetic-provider' });
  await api.closeRate('rate-id', { effective_to: '2030-01-01T00:00:00Z', reason: 'superseded' });
  await api.bindings('policy-id');
  await api.createBinding({ policy_version_id: 'policy-id' });
  await api.assignContract({ tenant_id: 'tenant-id', contract_ref: 'C-1', limits: { tracked_products: 10 } });

  assert.deepEqual(calls, [
    ['get', '/platform/billing/custom-plan-pricing/policies'],
    ['post', '/platform/billing/custom-plan-pricing/policies', { target_gross_margin: 0.4 }],
    ['post', '/platform/billing/custom-plan-pricing/policies/policy-id/activate', { approval_evidence: 'evidence' }],
    ['get', '/platform/billing/custom-plan-pricing/cost-rates'],
    ['post', '/platform/billing/custom-plan-pricing/cost-rates', { provider: 'synthetic-provider' }],
    ['post', '/platform/billing/custom-plan-pricing/cost-rates/rate-id/close', { effective_to: '2030-01-01T00:00:00Z', reason: 'superseded' }],
    ['get', '/platform/billing/custom-plan-pricing/policies/policy-id/bindings'],
    ['post', '/platform/billing/custom-plan-pricing/bindings', { policy_version_id: 'policy-id' }],
    ['post', '/platform/billing/custom-contracts', { tenant_id: 'tenant-id', contract_ref: 'C-1', limits: { tracked_products: 10 } }],
  ]);
});
