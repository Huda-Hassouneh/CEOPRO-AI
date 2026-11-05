import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { quoteHasVerifiedActivation, quoteIsExpired, subscriptionBlocksCustomCheckout, quoteFeatureLabel } from '../src/features/billing/utils/customQuoteState.js';
import { hasActivePlanAccess } from '../src/features/billing/utils/onboardingRouting.js';

test('expiry uses the exact authoritative cutoff, including after refresh and state transitions', () => {
  const cutoff = Date.parse('2026-11-05T12:00:00Z');
  for (const state of ['submitted', 'approved', 'accepted']) {
    const quote = { state, valid_until: '2026-11-05T15:00:00+03:00' };
    assert.equal(quoteIsExpired(quote, cutoff - 1), false);
    assert.equal(quoteIsExpired(quote, cutoff), true);
    assert.equal(quoteIsExpired(JSON.parse(JSON.stringify(quote)), cutoff + 1), true);
  }
  assert.equal(quoteIsExpired({ state: 'expired' }, cutoff), true);
  assert.equal(quoteIsExpired({ state: 'rejected', valid_until: '2020-01-01T00:00:00Z' }, cutoff), false);
});

test('existing Standard/Custom subscriptions block duplicate Checkout without changing existing rights', () => {
  for (const planId of ['starter', 'custom']) {
    const subscription = { hasSubscription: true, assigned: true, hasAccess: true, billingStatus: 'active', planId, limits: { products: 3 } };
    const before = JSON.stringify(subscription);
    assert.equal(subscriptionBlocksCustomCheckout(subscription), true);
    assert.equal(hasActivePlanAccess(subscription), true);
    assert.equal(JSON.stringify(subscription), before);
  }
  assert.equal(subscriptionBlocksCustomCheckout({ assigned: true, hasAccess: true, planId: 'custom' }), true);
  for (const billingStatus of ['trialing', 'pending', 'past_due', 'payment_failed', 'paused']) {
    assert.equal(subscriptionBlocksCustomCheckout({ hasSubscription: true, billingStatus }), true);
  }
  assert.equal(subscriptionBlocksCustomCheckout({ hasSubscription: false, assigned: false }), false);
  assert.equal(subscriptionBlocksCustomCheckout({ hasSubscription: false, assigned: true, source: 'trial', billingStatus: 'trialing', planId: 'growth' }), false);
  assert.equal(subscriptionBlocksCustomCheckout({ hasSubscription: false, billingStatus: 'cancelled' }), false);
});

test('numeric feature labels use the existing localized catalog, then modules, then a readable fallback', () => {
  for (const locale of ['en', 'ar']) {
    const messages = JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`, import.meta.url), 'utf8'));
    const t = key => key.split('.').reduce((value, part) => value?.[part], messages) || key;
    assert.equal(quoteFeatureLabel(t, 'ai_credits'), messages.billing.customPlan.featureNames.ai_credits);
    assert.equal(quoteFeatureLabel(t, 'market_intelligence'), messages.billing.modules.market_intelligence);
    assert.equal(quoteFeatureLabel(t, 'future_feature'), 'future feature');
    assert.ok(!messages.billing.customPlan.pendingTitle.includes('?'));
    if (locale === 'ar') assert.match(messages.billing.customPlan.pendingTitle, /[\u0600-\u06ff]/);
  }
});

test('quote acceptance and a redirect do not imply verified paid activation', () => {
  assert.equal(quoteHasVerifiedActivation({state:'accepted',events:[{action:'accepted'}]}),false);
  assert.equal(quoteHasVerifiedActivation({state:'accepted',events:[{action:'checkout_session_completed'}]}),false);
  assert.equal(quoteHasVerifiedActivation({events:[{action:'contract_activated'}]}),true);
});
test('Custom Arabic translations have readable text and matching interpolation keys', () => {
  const en=JSON.parse(readFileSync(new URL('../src/assets/locales/en.json',import.meta.url),'utf8')).billing.customPlan;
  const ar=JSON.parse(readFileSync(new URL('../src/assets/locales/ar.json',import.meta.url),'utf8')).billing.customPlan;
  const visit=(left,right)=>Object.entries(left).forEach(([key,value])=>{
    if(typeof value==='object')return visit(value,right[key]);
    assert.equal(typeof right[key],'string',key);
    assert.ok(!right[key].includes('??'),key);
    assert.deepEqual(right[key].match(/\{\{\w+\}\}/g)||[],value.match(/\{\{\w+\}\}/g)||[],key);
  });visit(en,ar);
});

test('final vendor ratio review has readable English and Arabic explanations', () => {
  for (const locale of ['en', 'ar']) {
    const messages = JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`, import.meta.url), 'utf8'));
    for (const reason of ['VENDOR_COST_RATIO_EXCEEDED', 'VENDOR_COST_RATIO_UNVERIFIABLE']) {
      const explanation = messages.billing.customPlan.reviewReasons[reason];
      assert.ok(explanation.length > 20);
      assert.ok(!explanation.includes(reason));
      if (locale === 'ar') assert.match(explanation, /[\u0600-\u06ff]/);
    }
  }
});
