import test from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_helpers.mjs';

test('37.01 normal billing keeps Custom Plan as a separate builder route', async () => {
  const choose = await read('src/features/billing/pages/ChoosePlanPage.jsx');
  const routes = await read('src/app/router/routePaths.js');

  assert.match(choose, /id:\s*["']custom["']/);
  assert.match(choose, /isCustomBuilder:\s*true/);
  assert.match(choose, /routePaths\.billingCustomPlan/);
  assert.match(routes, /billingCustomPlan:\s*["']\/billing\/plans\/custom["']/);
});

test('37.02 onboarding keeps Custom Plan separate from standard plan IDs', async () => {
  const page = await read('src/features/onboarding/pages/OnboardingPlanSelectionPage.jsx');
  assert.match(page, /selectedPlan\s*===\s*["']custom["']/);
  assert.match(page, /navigate\(routePaths\.onboardingPlanCustom\)/);
  assert.match(page, /showCustomPlan/);
});

test('37.03 custom checkout stays server-authoritative and does not send browser price', async () => {
  const payment = await read('src/features/onboarding/pages/OnboardingPaymentPage.jsx');
  assert.match(payment, /billingApi\.checkoutCustomPlan\(\{/);
  assert.match(payment, /features:\s*customPlanSelection/);
  assert.match(payment, /billingPeriod/);
  assert.match(payment, /paymentMethod:\s*["']stripe["']/);

  const checkoutCall = payment.match(/billingApi\.checkoutCustomPlan\(\{[\s\S]*?\}\);/)?.[0] ?? '';
  assert.doesNotMatch(checkoutCall, /\b(?:price|amount|currency|monthlyPrice)\s*:/);
});
