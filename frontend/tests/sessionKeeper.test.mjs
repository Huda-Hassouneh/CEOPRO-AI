import test from 'node:test';
import assert from 'node:assert/strict';
import { needsEmailVerification, shouldRenew, tokenTimes } from '../src/features/auth/sessionKeeper.js';

// An unsigned token with the given claims - only the payload is read client-side.
const token = (claims) => `x.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.y`;
const MIN = 60 * 1000;
const now = Date.UTC(2026, 9, 9, 12, 0, 0);
const at = (ms) => Math.floor(ms / 1000);

test('tokenTimes reads expiry and issue time; garbage yields null', () => {
  assert.deepEqual(tokenTimes(token({ exp: at(now), iat: at(now - 60 * MIN) })), { expiresAt: now, issuedAt: now - 60 * MIN });
  assert.equal(tokenTimes('not-a-jwt'), null);
  assert.equal(tokenTimes(token({ sub: 'no exp' })), null);
});

test('renews shortly before expiry when the user has been active since the token was issued', () => {
  const t = token({ exp: at(now + 5 * MIN), iat: at(now - 115 * MIN) });
  assert.equal(shouldRenew({ token: t, now, lastActivity: now - 30 * MIN }), true);
});

test('does not renew for an idle tab - it is left to expire', () => {
  const t = token({ exp: at(now + 5 * MIN), iat: at(now - 115 * MIN) });
  assert.equal(shouldRenew({ token: t, now, lastActivity: now - 120 * MIN }), false);
});

test('does not renew too early, or after expiry, or without a token', () => {
  assert.equal(shouldRenew({ token: token({ exp: at(now + 60 * MIN), iat: at(now - 60 * MIN) }), now, lastActivity: now }), false);
  assert.equal(shouldRenew({ token: token({ exp: at(now - MIN), iat: at(now - 121 * MIN) }), now, lastActivity: now }), false);
  assert.equal(shouldRenew({ token: null, now, lastActivity: now }), false);
});

test('older tokens without an issue time renew on recent activity only', () => {
  const t = token({ exp: at(now + 5 * MIN) });
  assert.equal(shouldRenew({ token: t, now, lastActivity: now - 2 * MIN }), true);
  assert.equal(shouldRenew({ token: t, now, lastActivity: now - 60 * MIN }), false);
});

test('email confirmation is needed only when the token says it was required and not done', () => {
  assert.equal(needsEmailVerification(token({ exp: 1, evr: true, ev: false })), true);
  assert.equal(needsEmailVerification(token({ exp: 1, evr: true, ev: true })), false);
  assert.equal(needsEmailVerification(token({ exp: 1, evr: false, ev: false })), false);
  assert.equal(needsEmailVerification(token({ exp: 1 })), false, 'older tokens without the claims are not sent to the code screen');
  assert.equal(needsEmailVerification(null), false);
  assert.equal(needsEmailVerification('not-a-token'), false);
});
