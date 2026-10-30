import test from 'node:test';
import assert from 'node:assert/strict';
import { isExpectedPlatformMeDenial } from './browser/response-policy.mjs';

const options = { expectedTenantFixture: true, apiUrl: 'http://localhost:8000' };
const request = (status, method = 'GET', url = 'http://localhost:8000/platform/me') => ({ status, method, url });

test('recognizes only the expected tenant fixture GET denial for /platform/me', () => {
  assert.equal(isExpectedPlatformMeDenial(request(403), options), true);
});

test('does not ignore other denied endpoints, methods, statuses, or API origins', () => {
  assert.equal(isExpectedPlatformMeDenial(request(403, 'GET', 'http://localhost:8000/platform/users'), options), false);
  assert.equal(isExpectedPlatformMeDenial(request(403, 'PATCH'), options), false);
  assert.equal(isExpectedPlatformMeDenial(request(401), options), false);
  assert.equal(isExpectedPlatformMeDenial(request(403, 'GET', 'http://other-host/platform/me'), options), false);
  assert.equal(isExpectedPlatformMeDenial(request(403), { ...options, expectedTenantFixture: false }), false);
});
