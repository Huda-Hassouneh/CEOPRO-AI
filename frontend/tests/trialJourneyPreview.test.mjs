import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import httpClient from '../src/shared/lib/httpClient.js';
import { getTrialJourneyPreview, trialJourneyPreviewEnabled, trialPreviewQuery, validTrialOperation } from '../src/features/billing/api/trialJourneyApi.js';

const operation = '11111111-1111-4111-8111-111111111111';

test('preview defaults off; disabled/missing identity/invalid operation cannot fetch', () => {
  assert.equal(trialJourneyPreviewEnabled, false);
  for (const args of [['t','u',operation,false], [null,'u',operation,true], ['t',null,operation,true], ['t','u','latest',true]]) {
    assert.equal(trialPreviewQuery(...args).enabled, false);
  }
  assert.equal(validTrialOperation('../checkout'), false);
  assert.equal(validTrialOperation(operation), true);
});

test('cache identity includes tenant, actor and exact operation; retries disabled', () => {
  const query = trialPreviewQuery('tenant', 'actor', operation, true);
  assert.deepEqual(query.queryKey, ['trialJourneyPreview', 'tenant', 'actor', operation]);
  assert.equal(query.enabled, true);
  assert.equal(query.retry, false);
  assert.equal(query.gcTime, 0);
  assert.notDeepEqual(query.queryKey, trialPreviewQuery('other', 'actor', operation, true).queryKey);
  assert.notDeepEqual(query.queryKey, trialPreviewQuery('tenant', 'other', operation, true).queryKey);
});

test('only a GET for the exact UUID is sent; response mismatch fails closed', async () => {
  const original = httpClient.defaults.adapter; const calls = [];
  let returned = operation;
  httpClient.defaults.adapter = async config => {
    calls.push(config);
    return { data: { operation_id: returned, state: 'pending_verification' }, status: 200, statusText: 'OK', config, headers: {} };
  };
  try {
    assert.equal((await getTrialJourneyPreview(operation)).state, 'pending_verification');
    assert.equal(calls[0].method, 'get');
    assert.equal(calls[0].url, `/billing/trial-journeys/${operation}`);
    assert.equal(calls[0].data, undefined);
    returned = '22222222-2222-4222-8222-222222222222';
    await assert.rejects(getTrialJourneyPreview(operation), /Operation mismatch/);
    await assert.rejects(getTrialJourneyPreview('latest'), /UUID required/);
    assert.equal(calls.length, 2);
  } finally { httpClient.defaults.adapter = original; }
});

test('integration adds only the preview panel; it does not drive onboarding or payment actions', () => {
  const component = readFileSync(new URL('../src/features/billing/components/TrialJourneyPreview.jsx', import.meta.url), 'utf8');
  assert.ok(component.includes('return enabled ? <EnabledPreview'));
  assert.ok(component.includes('!query.isError && !query.isFetching'));
  assert.ok(!/useMutation|navigate|startTrial|checkout\(|acceptConsent|localStorage|hasAccess/.test(component));
  const page = readFileSync(new URL('../src/features/billing/pages/OnboardingPaymentPage.jsx', import.meta.url), 'utf8');
  assert.ok(page.includes("<TrialJourneyPreview operationId={searchParams.get('trial_operation')} />"));
});
