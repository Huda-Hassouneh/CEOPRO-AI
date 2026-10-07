import test from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_helpers.mjs';

test('38.01 standard checkout sends plan identity + period, never a browser-owned amount', async () => {
  const hook = await read('src/features/billing/hooks/useCheckout.js');
  const payload = hook.match(/const payload = \{[\s\S]*?\n\s*\};/)?.[0] ?? '';

  assert.match(payload, /planId/);
  assert.match(payload, /billing_period:\s*billingPeriod/);
  assert.match(payload, /payment_method:\s*method/);
  assert.doesNotMatch(payload, /\b(?:amount|price|currency|unit_amount)\s*:/);
});

test('38.02 billing checkout page uses server-owned plan IDs and Stripe checkout URL', async () => {
  const page = await read('src/features/billing/pages/BillingCheckoutPage.jsx');
  assert.match(page, /billingApi\.createCheckout\(\{/);
  assert.match(page, /planId:\s*selectedPlan\.id/);
  assert.match(page, /billing_period:/);
  assert.match(page, /payment_method:\s*["']stripe["']/);
  assert.doesNotMatch(page, /amount:\s*selectedPlan|price:\s*selectedPlan/);
});

test('38.03 checkout hook requires an authoritative redirect URL', async () => {
  const hook = await read('src/features/billing/hooks/useCheckout.js');
  assert.match(hook, /CHECKOUT_URL_MISSING/);
  assert.match(hook, /window\.location\.assign\(checkoutUrl\)/);
});
