import test from 'node:test';
import assert from 'node:assert/strict';
import { mapPlan } from '../src/features/billing/api/billingApi.js';

test('plan limits show only the customer-facing terms, never internal budgets as raw codes', () => {
  const plan = mapPlan({ plan_key: 'starter', limits: { tracked_products: 250, web_searches: 100, document_storage_mb: 1024 }, prices: [], entitlements: [] });
  assert.deepEqual(plan.limits, { products: 250, storageGb: 1 });
});
