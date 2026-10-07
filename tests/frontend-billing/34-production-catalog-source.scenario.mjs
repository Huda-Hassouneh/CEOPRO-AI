import test from 'node:test';
import assert from 'node:assert/strict';
import { read, readMany, customerBillingFiles } from './_helpers.mjs';

test('34.01 standard plan selection is API-driven in billing and onboarding', async () => {
  const choose = await read('src/features/billing/pages/ChoosePlanPage.jsx');
  const onboarding = await read('src/features/onboarding/pages/OnboardingPlanSelectionPage.jsx');
  const api = await read('src/features/billing/api/billingApi.js');

  assert.match(api, /plans:\s*["']\/subscription\/plans["']/);
  assert.match(api, /getPlans:\s*\(\)\s*=>\s*unwrap\(httpClient\.get\(endpoints\.plans\)\)/);
  assert.match(choose, /useSWR\([\s\S]*billingApi\.getPlans/);
  assert.match(onboarding, /useSWR\([\s\S]*billingApi\.getPlans/);
});

test('34.02 customer plan pages do not import preview/mock plan catalogs', async () => {
  const code = await readMany(customerBillingFiles);
  assert.doesNotMatch(code, /billingPreviewData|subscriptionPreviewData|PREVIEW_PLANS|previewAdapter/);
});

test('34.03 plan identity and prices come from backend plan objects rather than hardcoded production prices', async () => {
  const choose = await read('src/features/billing/pages/ChoosePlanPage.jsx');
  const selector = await read('src/features/billing/components/PlanSelector.jsx');
  const card = await read('src/features/billing/components/PlanCard.jsx');

  assert.match(choose, /plan\.name/);
  assert.match(choose, /plan\.pricingOptions/);
  assert.match(card, /selectedPricingOption\?\.totalPrice\s*\?\?\s*plan\.basePrice/);
  assert.doesNotMatch(`${choose}\n${selector}`, /\b(?:55|140|350)\s*(?:USD|usd)/);
});
