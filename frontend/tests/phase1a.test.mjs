import test from 'node:test';
import assert from 'node:assert/strict';
import httpClient from '../src/shared/lib/httpClient.js';
import { platformApi, platformInvitationErrorKey } from '../src/features/platform/platformApi.js';
import { toSession } from '../src/features/auth/api/authHttpAdapter.js';
import { savePendingRegistration, readPendingRegistration, clearPendingRegistration, registrationFields } from '../src/features/auth/pendingRegistration.js';
const storage = () => { const map = new Map(); return { getItem: (key) => map.get(key) ?? null, setItem: (key, value) => map.set(key, value), removeItem: (key) => map.delete(key) }; };

test('pending registration stores only an email-bound challenge, never password or JWT', () => {
  const store = storage(); savePendingRegistration({ email: 'owner@example.test', registration_token: 'nonce', password: 'never-store', access_token: 'not-a-session' }, store);
  assert.deepEqual(readPendingRegistration(store), { email: 'owner@example.test', registration_token: 'nonce' });
  assert.deepEqual(registrationFields('OTHER@example.test', store), {});
  assert.deepEqual(registrationFields('OWNER@example.test', store), { registration_token: 'nonce' });
  clearPendingRegistration(store); assert.equal(readPendingRegistration(store), null);
  assert.equal(toSession({ status: 'pending_verification', registration_token: 'nonce' }), null);
});
test('storage failure retains same-tab verification and clear works', () => {
  const unavailable = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); } };
  savePendingRegistration({ email: 'owner@example.test', registration_token: 'nonce' }, unavailable);
  assert.equal(readPendingRegistration(unavailable).registration_token, 'nonce');
  clearPendingRegistration(unavailable); assert.equal(readPendingRegistration(unavailable), null);
});
test('platform API uses existing bearer HTTP client and explicit bounded management contracts', async () => {
  const original = httpClient.defaults.adapter; const calls = [];
  httpClient.defaults.adapter = async (config) => { calls.push(config); return { data: { items: [] }, status: 200, statusText: 'OK', config, headers: {} }; };
  try {
    await platformApi.read('companies', 50); await platformApi.read('companies', 0, 'North Shop'); await platformApi.read('users', 100, 'person@example.test');
    await platformApi.companyStatus('id', { active: false, reason: 'incident' });
    await platformApi.member('user', { status: 'suspended', reason: 'offboard' }); await platformApi.invitationAction('invite', 'resend', 'retry');
    assert.equal(calls[0].url, '/platform/companies'); assert.deepEqual(calls[0].params, { limit: 50, offset: 50 });
    assert.deepEqual(calls[1].params, { limit: 50, offset: 0, search: 'North Shop' });
    assert.deepEqual(calls[2].params, { limit: 50, offset: 100, search: 'person@example.test' });
    assert.equal(calls[3].method, 'patch'); assert.equal(calls[3].url, '/platform/companies/id/status');
    assert.deepEqual(JSON.parse(calls[3].data), { active: false, reason: 'incident' });
    assert.equal(calls[4].url, '/platform/team/user'); assert.equal(calls[5].url, '/platform/team/invitations/invite/resend');
  } finally { httpClient.defaults.adapter = original; }
});
test('platform public invitation and owner approval preserve distinct endpoints and idempotency data', async () => {
  const original = httpClient.defaults.adapter; const calls = [];
  httpClient.defaults.adapter = async (config) => { calls.push(config); return { data: {}, status: 200, statusText: 'OK', config, headers: {} }; };
  try {
    await platformApi.invitation('a/b'); await platformApi.accept('a/b', { full_name: 'Owner', password: 'password' });
    await platformApi.approve({ request_id: 'stable-request', kind: 'manual_access', terms: { reference: 'approved' } });
    assert.equal(calls[0].url, '/platform/invitations/a%2Fb');
    assert.equal(calls[1].url, '/platform/invitations/a%2Fb/accept');
    assert.equal(JSON.parse(calls[2].data).request_id, 'stable-request');
    assert.equal(calls[2].url, '/platform/financial-approvals');
    assert.throws(() => platformApi.read('billing-activate'));
    assert.throws(() => platformApi.invitationAction('id', 'promote-owner', 'invalid'));
  } finally { httpClient.defaults.adapter = original; }
});

test('invitation errors distinguish expiry, credentials, conflicts and dependency failures', () => {
  assert.equal(platformInvitationErrorKey({ response: { status: 404 } }), 'platform.invitationInvalid');
  assert.equal(platformInvitationErrorKey({ response: { status: 422 } }), 'platform.newCredentials');
  assert.equal(platformInvitationErrorKey({ response: { status: 409 } }), 'platform.conflict');
  assert.equal(platformInvitationErrorKey({ response: { status: 503 } }), 'platform.failed');
  assert.equal(platformInvitationErrorKey(new Error('network down')), 'platform.failed');
});
