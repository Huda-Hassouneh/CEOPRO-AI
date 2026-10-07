import test from 'node:test';
import assert from 'node:assert/strict';
import { read, readMany, customerBillingFiles } from './_helpers.mjs';

test('40.01 customer billing flow contains no development-showcase or preview-plan dependency', async () => {
  const code = await readMany(customerBillingFiles);
  assert.doesNotMatch(code, /Development Showcase/i);
  assert.doesNotMatch(code, /PREVIEW_PLANS|billingPreviewData|subscriptionPreviewData/);
});

test('40.02 plan-card icon map recognizes only the requirements-aligned production tier names', async () => {
  const card = await read('src/features/billing/components/PlanCard.jsx');
  for (const tier of ['starter', 'growth', 'enterprise']) {
    assert.match(card, new RegExp(`\\b${tier}\\s*:`), `Missing icon mapping for ${tier}`);
  }
  assert.doesNotMatch(card, /\bstandard\s*:|\bpro\s*:/i);
});

test('40.03 customer-facing standard plan files do not hardcode JOD', async () => {
  const files = [
    'src/features/billing/pages/ChoosePlanPage.jsx',
    'src/features/billing/pages/BillingCheckoutPage.jsx',
    'src/features/billing/components/PlanCard.jsx',
    'src/features/billing/components/PlanSummaryCard.jsx',
    'src/features/onboarding/pages/OnboardingPlanSelectionPage.jsx',
    'src/features/onboarding/pages/OnboardingPaymentPage.jsx',
  ];
  const code = await readMany(files);
  assert.doesNotMatch(code, /["']JOD["']/);
});

test('40.04 landing pricing is API-driven and marketing CTAs do not persist a stale hardcoded plan ID', async () => {
  const pricing = await read('src/features/landing/sections/PricingSection.jsx');
  const primitives = await read('src/features/landing/components/LandingPrimitives.jsx');
  const hero = await read('src/features/landing/sections/HeroSection.jsx');
  const value = await read('src/features/landing/sections/ValueSections.jsx');
  const combined = `${pricing}\n${primitives}\n${hero}\n${value}`;

  assert.match(pricing, /billingApi\.getPlans/);
  assert.doesNotMatch(combined, /getPreviewPlan|billingPreviewData|PREVIEW_PLANS/);
  assert.doesNotMatch(primitives, /setPlanChoice\(["']pro["']/i);
});

test('40.05 onboarding recommendation resolves Starter and Growth by plan identity instead of array position', async () => {
  const page = await read('src/features/onboarding/pages/OnboardingPlanSelectionPage.jsx');
  const recommendation = await read('src/features/billing/components/StandardPlanRecommendation.jsx');

  assert.match(page, /findNamedPlan\(plans, ['"]starter['"]\)/);
  assert.match(page, /findNamedPlan\(plans, ['"]growth['"]\)/);
  assert.doesNotMatch(page, /plans\[1\]/);
  assert.doesNotMatch(recommendation, /onTryPro|onContinueStandard|tryPro|continueStandard/);
});
