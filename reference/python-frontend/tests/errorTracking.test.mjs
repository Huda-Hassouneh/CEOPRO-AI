import test from 'node:test';
import assert from 'node:assert/strict';
import { reportError, scrubBreadcrumb, scrubEvent } from '../src/shared/lib/errorTracking.js';

test('scrubEvent drops the user, headers, cookies and query strings', () => {
  const event = scrubEvent({
    user: { email: 'owner@example.com' },
    request: { url: 'https://app.example/reset?code=123#x', headers: { Authorization: 'Bearer t' }, cookies: 'a=b', query_string: 'code=123' },
  });
  assert.equal(event.user, undefined);
  assert.deepEqual(event.request, { url: 'https://app.example/reset' });
});

test('scrubBreadcrumb drops console output and strips query strings from URLs', () => {
  assert.equal(scrubBreadcrumb({ category: 'console', message: 'token=abc' }), null);
  const crumb = scrubBreadcrumb({ category: 'fetch', data: { url: 'https://api.example/x?token=abc', method: 'GET' } });
  assert.equal(crumb.data.url, 'https://api.example/x');
  const nav = scrubBreadcrumb({ category: 'navigation', data: { from: '/a?x=1', to: '/b?code=2' } });
  assert.deepEqual(nav.data, { from: '/a', to: '/b' });
});

test('reportError is a no-op when tracking is off (no DSN)', () => {
  assert.doesNotThrow(() => reportError(new Error('ignored')));
});
