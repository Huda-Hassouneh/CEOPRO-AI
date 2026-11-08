import test from 'node:test';
import assert from 'node:assert/strict';
import httpClient from '../src/shared/lib/httpClient.js';
import { subscriptionJourneyEnabled, subscriptionJourneyApi as api, journeyRequestKey } from '../src/features/billing/api/subscriptionJourneyApi.js';
import { expireTrialSnapshot, hasActivePlanAccess } from '../src/features/billing/utils/onboardingRouting.js';
const op='11111111-1111-4111-8111-111111111111';

test('default-off; request identities stable and isolated by tenant actor and terms', () => {
  assert.equal(subscriptionJourneyEnabled,false);
  const map=new Map(), storage={getItem:k=>map.get(k),setItem:(k,v)=>map.set(k,v)};
  const first=journeyRequestKey('tenant','actor','growth','monthly',storage);
  assert.equal(first,journeyRequestKey('tenant','actor','growth','monthly',storage));
  for (const values of [['other','actor','growth','monthly'],['tenant','other','growth','monthly'],['tenant','actor','growth','yearly']]) {
    assert.notEqual(first,journeyRequestKey(...values,storage));
  }
});

test('only operation selectors are sent; progress is read-only; recovery never creates a new request', async () => {
  const original=httpClient.defaults.adapter,calls=[];
  httpClient.defaults.adapter=async config=>{calls.push(config);return {data:{operation_id:op,state:'pending'},status:200,statusText:'OK',headers:{},config};};
  try {
    await api.start('growth','monthly',op);await api.progress(op);await api.advance(op,'ar');await api.cleanup(op);await api.cancel(op);
    assert.deepEqual(JSON.parse(calls[0].data),{plan_key:'growth',period_code:'monthly',request_key:op});
    assert.equal(calls[1].method,'get');assert.deepEqual(JSON.parse(calls[2].data),{language:'ar'});
    assert.equal(calls.filter(c=>c.url==='/billing/trial-journeys').length,1);
    await assert.rejects(api.advance('../checkout','en'),/operation/);
  } finally {httpClient.defaults.adapter=original;}
});

test('exact trial cutoff removes cached browser access; redirect and checkpoint cannot grant', () => {
  const end='2026-11-08T12:00:00Z',now=Date.parse(end);
  const trial={assigned:true,hasAccess:true,billingStatus:'trialing',trialEndsAtExact:end};
  assert.equal(hasActivePlanAccess(expireTrialSnapshot(trial,now-1)),true);
  assert.equal(hasActivePlanAccess(expireTrialSnapshot(trial,now)),false);
  assert.equal(hasActivePlanAccess({state:'confirmed',checkout:'success'}),false);
  const paid={assigned:true,hasAccess:true,billingStatus:'active',trialEndsAtExact:end};
  assert.equal(expireTrialSnapshot(paid,now),paid);
});


test('durable conflict expiry and confirmation override cached advance results', async () => {
  const { journeyState } = await import('../src/features/billing/utils/subscriptionJourneyState.js');
  for (const state of ['conflict','expired','confirmed','blocked']) {
    assert.equal(journeyState({data:{state}}, {data:{state:'checkout_ready'}}),state);
  }
  assert.equal(journeyState({isError:true,data:{state:'confirmed'}},{data:{state:'checkout_ready'}}),'blocked');
});

test('neutral paid access expires without a webhook and paid cancellation preserves the cutoff', () => {
  const end='2026-11-08T12:00:00Z',now=Date.parse(end);
  const paid={assigned:true,hasAccess:true,billingStatus:'active',accessEndsAt:end,cancelAtPeriodEnd:true};
  assert.equal(hasActivePlanAccess(expireTrialSnapshot(paid,now-1)),true);
  assert.equal(hasActivePlanAccess(expireTrialSnapshot(paid,now)),false);
});


test('Checkout navigation requires the bound provider and explicitly installed Paddle origin', async () => {
  const { journeyCheckoutUrl } = await import('../src/features/billing/utils/subscriptionJourneyState.js');
  const paddle = {state:'checkout_ready',provider:'paddle',url:'https://merchant.example.test/payment?_ptxn=txn_synthetic'};
  assert.equal(journeyCheckoutUrl(paddle),null);
  assert.equal(journeyCheckoutUrl(paddle,'https://merchant.example.test'),paddle.url);
  assert.equal(journeyCheckoutUrl({...paddle,url:'https://user@merchant.example.test/payment'},'https://merchant.example.test'),null);
  assert.equal(journeyCheckoutUrl({...paddle,url:'https://wrong.example.test'},'https://merchant.example.test'),null);
});
