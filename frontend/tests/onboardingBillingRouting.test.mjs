import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  getOnboardingReturnPath,
  getPostSetupPath,
  hasActivePlanAccess,
  hasCurrentTrialAccess,
  canStartPlanTrial,
  ONBOARDING_RETURN_PATH_KEY,
} from '../src/features/billing/utils/onboardingRouting.js';

const storage = (value) => ({ getItem: () => value });

test('trial eligibility belongs to the selected plan, with no default Plus fallback', () => {
  const fresh = {trialAvailable:true,trialUsed:false,assigned:false,hasSubscription:false,trialEligiblePlanIds:['starter','enterprise']};
  for (const [id,days,expected] of [['starter',14,true],['growth',14,false],['enterprise',7,true],['no-trial',0,false]]) {
    assert.equal(canStartPlanTrial(fresh,{id,trialDays:days,selfServe:true}),expected);
  }
  assert.equal(canStartPlanTrial({...fresh,trialUsed:true},{id:'enterprise',trialDays:7,selfServe:true}),false);
  assert.equal(canStartPlanTrial({...fresh,assigned:true},{id:'enterprise',trialDays:7,selfServe:true}),false);
  assert.equal(canStartPlanTrial({...fresh,hasSubscription:true},{id:'enterprise',trialDays:7,selfServe:true}),false);
});

test('continue with current trial requires a real issued trial with backend-confirmed access', () => {
  const issued = {assigned:true,hasAccess:true,billingStatus:'trialing',trialUsed:true,trialEndsAt:'2026-11-16T07:37:20Z'};
  assert.equal(hasCurrentTrialAccess(issued),true);
  for (const changes of [{assigned:false},{hasAccess:false},{billingStatus:'expired'},{trialUsed:false},{trialEndsAt:null},{billingStatus:'active'}]) {
    assert.equal(hasCurrentTrialAccess({...issued,...changes}),false);
  }
});

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

test('no trial is offered when the server cannot collect a payment method', () => {
  const eligible = { trialUsed: false, assigned: false, hasSubscription: false, trialEligiblePlanIds: ['growth'] };
  const plan = { id: 'growth', trialDays: 14, selfServe: true };
  assert.equal(canStartPlanTrial({ ...eligible, paymentsEnabled: true }, plan), true);
  assert.equal(canStartPlanTrial({ ...eligible, paymentsEnabled: false }, plan), false);
  assert.equal(canStartPlanTrial(eligible, plan), true, 'older responses without the flag keep working');
});
