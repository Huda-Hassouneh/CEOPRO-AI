import test from 'node:test';
import assert from 'node:assert/strict';
import { billingErrorMessage, checkoutConfirmationState, mapPlan } from '../src/features/billing/api/billingApi.js';
import { readFileSync } from 'node:fs';

test('pending/reconciliation errors are localized and unknown codes never show raw keys', () => {
  for (const locale of ['en', 'ar']) {
    const labels = JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`, import.meta.url), 'utf8'));
    const t = key => key.split('.').reduce((value, part) => value?.[part], labels) ?? key;
    for (const reason of ['checkout_pending', 'checkout_reconciling', 'checkout_reconciliation_required', 'trial_checkout_pending', 'customer_creation_reconciling', 'customer_identity_conflict', 'unrecognized_future_code']) {
      if (reason !== 'unrecognized_future_code') assert.equal(typeof labels.billing.errors[reason], 'string');
      const message = billingErrorMessage({ response: { data: { detail: { reason } } } }, t);
      assert.ok(message.length > 20);
      assert.ok(!message.includes('billing.errors.'));
      if (reason === 'unrecognized_future_code') assert.equal(message, t('billing.errors.generic'));
    }
  }
});

test('Checkout return is pending until the backend confirms active billing state', () => {
  assert.equal(checkoutConfirmationState(null), 'pending');
  assert.equal(checkoutConfirmationState({ hasSubscription: false, status: 'none' }), 'pending');
  assert.equal(checkoutConfirmationState({ hasSubscription: true, status: 'failed' }), 'notConfirmed');
  assert.equal(checkoutConfirmationState({ hasSubscription: true, status: 'expired' }), 'notConfirmed');
  assert.equal(checkoutConfirmationState({ hasSubscription: true, status: 'active' }), 'confirmed');
  assert.equal(checkoutConfirmationState({ hasSubscription: true, status: 'trial' }), 'confirmed');
});

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
import httpClient from '../src/shared/lib/httpClient.js';

test('checkout sends only server-verifiable plan and period fields to the Python billing API', async () => {
  const original = httpClient.defaults.adapter; const calls = [];
  httpClient.defaults.adapter = async (config) => { calls.push(config); return { data: { url: 'https://checkout.example.test/session' }, status: 200, statusText: 'OK', config, headers: {} }; };
  try {
    const { billingApi } = await import('../src/features/billing/api/billingApi.js');
    await billingApi.checkout({ planId: 'growth', billingPeriod: 'monthly' });
    assert.equal(calls[0].url, '/billing/checkout');
    assert.deepEqual(JSON.parse(calls[0].data), { plan_key: 'growth', period_code: 'monthly' });
  } finally { httpClient.defaults.adapter = original; }
});

test('trial selection uses the Python trial endpoint and sends no client-controlled price', async () => {
  const original = httpClient.defaults.adapter; const calls = [];
  httpClient.defaults.adapter = async (config) => { calls.push(config); return { data: { plan_key: 'growth' }, status: 200, statusText: 'OK', config, headers: {} }; };
  try {
    const { billingApi } = await import('../src/features/billing/api/billingApi.js');
    await billingApi.startTrial({ planId: 'growth' });
    assert.equal(calls[0].url, '/billing/trial');
    assert.deepEqual(JSON.parse(calls[0].data), { plan_key: 'growth', period_code: 'monthly' });
  } finally { httpClient.defaults.adapter = original; }
});
