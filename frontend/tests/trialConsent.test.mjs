import test from 'node:test';
import assert from 'node:assert/strict';
import httpClient from '../src/shared/lib/httpClient.js';
import { trialConsentApi, trialConsentEnabled } from '../src/features/billing/api/trialConsentApi.js';
const operation='11111111-1111-4111-8111-111111111111';

test('consent is default-off and unchecked values never submit', async () => {
  assert.equal(trialConsentEnabled,false);
  for (const checked of [false,1,'true',null]) await assert.rejects(trialConsentApi.accept(operation,'en',{},checked),/Unchecked/);
});

test('requests contain only original selectors and explicit acknowledgement', async () => {
  const original=httpClient.defaults.adapter;const calls=[];
  httpClient.defaults.adapter=async config => {
    calls.push(config);return {data:{operation_id:operation,state:'pending_policy'},status:200,statusText:'OK',headers:{},config};
  };
  try {
    await trialConsentApi.prepare(operation,'ar');
    await trialConsentApi.present(operation,'ar');
    const presentation={presentation_id:operation,challenge:'x'.repeat(72),actor_id:'injected',approved_amount:0};
    await trialConsentApi.accept(operation,'ar',presentation,true);
    await trialConsentApi.withdraw(operation,presentation);
    assert.equal(calls[0].method,'get');assert.deepEqual(calls[0].params,{language:'ar'});
    assert.deepEqual(JSON.parse(calls[2].data),{language:'ar',presentation_id:operation,challenge:'x'.repeat(72),checked:true});
    assert.deepEqual(JSON.parse(calls[3].data),{presentation_id:operation});
    assert.ok(calls.every(call=>call.url.startsWith(`/billing/trial-journeys/${operation}/consent/`)));
    await assert.rejects(trialConsentApi.prepare('../checkout','en'),/UUID/);
  } finally {httpClient.defaults.adapter=original;}
});
