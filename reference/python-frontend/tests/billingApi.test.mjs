import test from 'node:test';
import assert from 'node:assert/strict';
import { mapPlan } from '../src/features/billing/api/billingApi.js';

test('plan limits show only the customer-facing terms, never internal budgets as raw codes', () => {
  const plan = mapPlan({ plan_key: 'starter', limits: { tracked_products: 250, web_searches: 100, document_storage_mb: 1024 }, prices: [], entitlements: [] });
  assert.deepEqual(plan.limits, { products: 250, storageGb: 1 });
});

test('plans show reports, seats and both credit budgets, with the trial allowance, and no competitor count', () => {
  const plan = mapPlan({
    plan_key: 'enterprise', monthly_price: 350, trial_days: 7,
    limits: { tracked_products: 500, monthly_reports: 60, team_seats: 50, data_credits: 2780, ai_credits: 2780,
      tracked_competitors: null, rag_assistant: 2000000 },
    trial_limits: { data_credits: 278, ai_credits: 278 }, prices: [], entitlements: [],
  });
  assert.deepEqual(plan.limits, { products: 500, reports: 60, teamSeats: 50, dataCredits: 2780, aiCredits: 2780 });
  assert.deepEqual(plan.trialLimits, { dataCredits: 278, aiCredits: 278 });
  assert.equal(plan.trialDays, 7);
});
