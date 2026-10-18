import test from 'node:test';
import assert from 'node:assert/strict';
import { describeMarketingError } from '../src/features/marketing/lib/marketingErrors.js';
import en from '../src/assets/locales/en.json' with { type: 'json' };
import ar from '../src/assets/locales/ar.json' with { type: 'json' };

const failure = (status, data = {}, headers = {}) => ({ response: { status, data, headers } });
const planLimit = (detail) => failure(402, { detail: { reason: 'LIMIT_REACHED', reset_cycle: 'billing_period', ...detail } });

test('plan limits name the allowance that ran out and when it renews', () => {
  assert.deepEqual(describeMarketingError(planLimit({ feature_code: 'rag_assistant', period_end: '2026-10-31' })),
    { key: 'planTokens', billing: true, renewsOn: '2026-11-01' });
  assert.equal(describeMarketingError(planLimit({ feature_code: 'marketing_image_generation' }), { action: 'image' }).key, 'planImages');
  const storage = describeMarketingError(planLimit({ feature_code: 'document_storage_mb', reset_cycle: 'never', period_end: '2026-10-31' }), { action: 'upload' });
  assert.equal(storage.key, 'planStorage');
  assert.equal(storage.renewsOn, null); // storage doesn't renew
  assert.equal(describeMarketingError(planLimit({ feature_code: 'document_extraction' }), { action: 'upload' }).key, 'planUploads');
  assert.equal(describeMarketingError(planLimit({ feature_code: 'something_new' })).key, 'planOther');
  assert.equal(describeMarketingError(failure(402, { detail: { reason: 'SUBSCRIPTION_INACTIVE' } })).key, 'planInactive');
});

test('busy, unconfigured, offline and photo errors get their own explanation', () => {
  assert.deepEqual(describeMarketingError(failure(429, {}, { 'retry-after': '42' })), { key: 'busyFor', values: { seconds: 42 } });
  assert.deepEqual(describeMarketingError(failure(503)), { key: 'busy' });
  assert.equal(describeMarketingError(failure(503, {}, { 'x-assistant-reason': 'not_configured' })).key, 'notConfigured');
  assert.equal(describeMarketingError(new Error('Network Error')).key, 'offline');
  assert.equal(describeMarketingError(failure(422), { source: 'link' }).key, 'badLink');
  assert.equal(describeMarketingError(failure(422), { source: 'describe' }).key, 'failed');
  assert.equal(describeMarketingError(failure(413), { action: 'upload' }).key, 'photoTooLarge');
  assert.equal(describeMarketingError(failure(400), { action: 'upload' }).key, 'photoWrongType');
  assert.equal(describeMarketingError(failure(500), { action: 'image' }).key, 'imageFailed');
  assert.equal(describeMarketingError(failure(502), { action: 'photo' }).key, 'photoFailed');
});

test('every key the helper can return is translated in English and Arabic', () => {
  const keys = ['offline', 'notConfigured', 'busy', 'busyFor', 'badLink', 'failed', 'planTokens', 'planImages', 'planStorage',
    'planUploads', 'planOther', 'planInactive', 'renewsOn', 'openBilling', 'imageFailed', 'uploadFailed', 'photoFailed',
    'photoTooLarge', 'photoWrongType'];
  for (const key of keys) {
    assert.ok(en.marketingApex.errors[key], `en ${key}`);
    assert.ok(ar.marketingApex.errors[key], `ar ${key}`);
  }
});
