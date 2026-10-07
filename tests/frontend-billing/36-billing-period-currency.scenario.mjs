import test from 'node:test';
import assert from 'node:assert/strict';
import { listBillingPeriods } from '../../src/features/billing/utils/billingPeriodPresentation.js';
import { read } from './_helpers.mjs';

test('36.01 billing-period utility preserves the production 1/3/6 month ordering and discounts', () => {
  const plans = [{
    pricingOptions: [
      { period: 'six-months', months: 6, intervalUnit: 'month', intervalCount: 6, discountPercent: 20 },
      { period: 'monthly', months: 1, intervalUnit: 'month', intervalCount: 1, discountPercent: 0 },
      { period: 'three-months', months: 3, intervalUnit: 'month', intervalCount: 3, discountPercent: 10 },
    ],
  }];

  const periods = listBillingPeriods(plans);
  assert.deepEqual(periods.map((item) => item.period), ['monthly', 'three-months', 'six-months']);
  assert.deepEqual(periods.map((item) => item.discountPercent), [0, 10, 20]);
});

test('36.02 customer cards render the backend currency and use USD only as a safe fallback', async () => {
  const planCard = await read('src/features/billing/components/PlanCard.jsx');
  const summary = await read('src/features/billing/components/PlanSummaryCard.jsx');

  assert.match(planCard, /currency:\s*plan\.currency\s*\|\|\s*["']USD["']/);
  assert.match(summary, /currency:\s*plan\.currency\s*\|\|\s*["']USD["']/);
});

test('36.03 owner-created standard plans no longer default to unsupported JOD', async () => {
  const catalog = await read('src/features/billing/pages/BillingCatalogPage.jsx');
  assert.doesNotMatch(catalog, /currency:\s*plan\?\.currency\s*\?\?\s*["']JOD["']/);
  assert.match(catalog, /currency:\s*plan\?\.currency\s*\?\?\s*["']USD["']/);
});
