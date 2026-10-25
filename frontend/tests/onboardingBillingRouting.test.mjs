import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  getOnboardingReturnPath,
  getPostSetupPath,
  hasActivePlanAccess,
  ONBOARDING_RETURN_PATH_KEY,
} from '../src/features/billing/utils/onboardingRouting.js';

const storage = (value) => ({ getItem: () => value });

test('subscription review has one live route and is not shadowed by a legacy redirect', () => {
  const router = readFileSync(new URL('../src/app/router/index.jsx', import.meta.url), 'utf8');
  assert.equal((router.match(/path: routePaths\.billingCheckout/g) || []).length, 1);
  const redirects = router.match(/\.\.\.\[([^\]]+)\]\s*\.map\(\(path\)/)?.[1] || '';
  assert.ok(redirects.includes("'/checkout'"));
  assert.ok(!redirects.includes("'/billing/checkout'"));
});

test('only an assigned active or trialing plan with backend-confirmed access completes onboarding', () => {
  assert.equal(hasActivePlanAccess({ assigned: true, hasAccess: true, billingStatus: 'active' }), true);
  assert.equal(hasActivePlanAccess({ assigned: true, hasAccess: true, billingStatus: 'trialing' }), true);
  assert.equal(hasActivePlanAccess({ assigned: false, hasAccess: true, billingStatus: 'active' }), false);
  assert.equal(hasActivePlanAccess({ assigned: true, hasAccess: false, billingStatus: 'past_due' }), false);
  assert.equal(hasActivePlanAccess({ assigned: true, hasAccess: true, billingStatus: 'pending' }), false);
});

test('new accounts go to plan selection, existing subscriptions go to Billing, and active plans return to the app', () => {
  assert.equal(getPostSetupPath({ assigned: false, hasAccess: true, hasSubscription: false, billingStatus: 'active' }), '/onboarding/plan');
  assert.equal(getPostSetupPath({ assigned: true, hasAccess: false, hasSubscription: true, billingStatus: 'past_due' }), '/billing');
  assert.equal(getPostSetupPath({ assigned: true, hasAccess: true, hasSubscription: false, billingStatus: 'trialing' }), '/dashboard');
  assert.equal(getPostSetupPath(undefined), '/billing');
});

test('return path accepts only the setup destinations and defaults safely', () => {
  assert.equal(getOnboardingReturnPath(storage('/market')), '/market');
  assert.equal(getOnboardingReturnPath(storage('/dashboard')), '/dashboard');
  assert.equal(getOnboardingReturnPath(storage('//attacker.example')), '/dashboard');
  assert.equal(ONBOARDING_RETURN_PATH_KEY, 'keel.onboarding.returnPath');
});
