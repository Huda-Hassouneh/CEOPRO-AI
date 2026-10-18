import test from 'node:test';
import assert from 'node:assert/strict';
import { read } from './_helpers.mjs';

test('39.01 payment-success and onboarding success resolve through the subscription success UI', async () => {
  const router = await read('src/app/router/index.jsx');
  const routes = await read('src/app/router/routePaths.js');

  assert.match(routes, /paymentSuccess:\s*["']\/payment-success["']/);
  assert.match(routes, /onboardingPlanSuccess:\s*["']\/onboarding\/plan\/success["']/);
  assert.match(router, /OnboardingSubscriptionSuccessPage/);
});

test('39.02 onboarding payment supports both standard and custom checkout paths', async () => {
  const page = await read('src/features/onboarding/pages/OnboardingPaymentPage.jsx');
  assert.match(page, /const isCustom = selectedPlan === ["']custom["']/);
  assert.match(page, /checkout\.mutateAsync\(\{/);
  assert.match(page, /billingApi\.checkoutCustomPlan\(\{/);
});
