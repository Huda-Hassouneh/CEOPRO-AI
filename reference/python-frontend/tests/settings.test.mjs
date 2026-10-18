import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { getSettingsPermissions } from '../src/features/settings/permissions/settingsPermissions.js';
import { profileApi } from '../src/features/settings/api/profileApi.js';
import { companyApi } from '../src/features/settings/api/companyApi.js';
import { teamApi } from '../src/features/settings/api/teamApi.js';
import { securityApi } from '../src/features/settings/api/securityApi.js';
import { NOTIFICATION_GROUPS, preferencesApi } from '../src/features/settings/api/preferencesApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

// backend/src/ai/routers/settings.py's real _COMPANY_ADMIN_ROLES =
// {"owner", "admin"} - signup itself always assigns role_key='owner'
// (routers/auth.py), never 'admin', so 'owner' must be admin-tier here
// too or no real account owner could ever invite a teammate or edit
// company settings.
test('permissions grant the real backend admin tier (owner+admin), never legacy/unknown roles', () => {
  for (const role of ['ADMIN', ' admin ', 'owner', 'OWNER']) assert.equal(getSettingsPermissions([role]).canInviteMembers, true);
  for (const role of ['EDITOR', 'VIEWER', 'manager', 'accountant', 'staff', 'unknown']) {
    const permissions = getSettingsPermissions([role]);
    for (const action of ['canEditCompany', 'canInviteMembers', 'canManageRoles', 'canRemoveMembers']) assert.equal(permissions[action], false);
    assert.equal(permissions.canManageOwnSecurity, true);
  }
  assert.equal(getSettingsPermissions(['owner']).role, 'owner');
  assert.equal(getSettingsPermissions([]).canInviteMembers, false);
});

// api/*.js now call the real, mounted backend/src/ai/routers/settings.py
// endpoints (business-logic correctness of those endpoints themselves -
// last-owner protection, role validation, RLS scoping - is covered by
// backend/src/ai/tests/test_settings.py and this session's own live
// curl-based verification against a real Postgres + uvicorn instance,
// not re-tested here). What IS still worth a real test with no backend
// running: that each api function sends the right request shape and
// correctly translates the real response shape into what its component
// consumes. A tiny local HTTP server stands in for the real backend -
// same technique as the backend's own httpClient-facing contract, zero
// new dependencies.
test('api layer sends the real request shape and translates the real response shape', async (t) => {
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      res.setHeader('Content-Type', 'application/json');
      const parsed = body ? JSON.parse(body) : null;
      if (req.url === '/settings/profile' && req.method === 'GET') {
        return res.end(JSON.stringify({ user_id: 'u1', email: 'a@b.com', full_name: 'Account Name', preferred_language: 'en', email_verified: true }));
      }
      if (req.url === '/settings/profile' && req.method === 'PATCH') {
        assert.equal(parsed.full_name, 'New Name');
        return res.end(JSON.stringify({ user_id: 'u1', email: 'a@b.com', full_name: 'New Name', preferred_language: 'en', email_verified: true }));
      }
      if (req.url === '/settings/company' && req.method === 'GET') {
        return res.end(JSON.stringify({ business_name: 'Company', business_type: null, country_code: 'JO', primary_currency: 'JOD' }));
      }
      if (req.url === '/settings/company/target-markets' && req.method === 'GET') {
        return res.end(JSON.stringify({ target_markets: [
          { market_type: 'COUNTRY', country_code: 'AE', region_name: null },
          { market_type: 'COUNTRY', country_code: 'JO', region_name: null },
        ] }));
      }
      if (req.url === '/settings/company/target-markets' && req.method === 'PUT') {
        assert.deepEqual(parsed, { target_markets: [{ market_type: 'COUNTRY', country_code: 'EG', region_name: null }] });
        return res.end(JSON.stringify({ target_markets: [{ market_type: 'COUNTRY', country_code: 'EG', region_name: null }] }));
      }
      if (req.url === '/settings/team/members' && req.method === 'GET') {
        return res.end(JSON.stringify({ members: [{ tenant_user_id: 'tu1', user_id: 'u1', email: 'a@b.com', full_name: 'Account Name', role_key: 'owner', joined_at: '2026-01-01T00:00:00Z' }] }));
      }
      if (req.url === '/settings/team/invitations' && req.method === 'POST') {
        assert.deepEqual(parsed, { email: 'new@example.com', role_key: 'staff' });
        return res.end(JSON.stringify({ ok: true }));
      }
      if (req.url === '/settings/security/change-password' && req.method === 'POST') {
        assert.deepEqual(parsed, { current_password: 'old', new_password: 'new' });
        return res.end(JSON.stringify({ ok: true }));
      }
      if (req.url === '/settings/security/sessions' && req.method === 'GET') {
        return res.end(JSON.stringify({ sessions: [], note: 'stateless' }));
      }
      if (req.url === '/settings/notifications' && req.method === 'GET') {
        return res.end(JSON.stringify({ notification_preferences: { in_app: { stock: false }, email: {}, email_frequency: 'daily' }, email_verified: true, email_delivery_available: false }));
      }
      if (req.url === '/settings/notifications' && req.method === 'PATCH') {
        assert.deepEqual(parsed, { email: { pricing: false } });
        return res.end(JSON.stringify({ notification_preferences: { in_app: {}, email: { pricing: false }, email_frequency: 'weekly' }, email_verified: false, email_delivery_available: true }));
      }
      res.statusCode = 404;
      res.end(JSON.stringify({ detail: 'not found' }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const profile = await profileApi.getProfile();
  assert.equal(profile.profile.fullName, 'Account Name');
  assert.equal(profile.capabilities.updateProfile, true);
  const updated = await profileApi.updateProfile({ fullName: 'New Name' });
  assert.equal(updated.persisted, true);
  assert.equal(updated.profile.fullName, 'New Name');

  const company = await companyApi.getCompany();
  assert.equal(company.company.name, 'Company');
  assert.equal(company.company.currency, 'JOD');

  assert.deepEqual(await companyApi.getTargetMarkets(), [
    { market_type: 'COUNTRY', country_code: 'AE', region_name: null },
    { market_type: 'COUNTRY', country_code: 'JO', region_name: null },
  ]);
  assert.deepEqual(
    await companyApi.updateTargetMarkets([{ market_type: 'COUNTRY', country_code: 'EG', region_name: null }]),
    [{ market_type: 'COUNTRY', country_code: 'EG', region_name: null }],
  );

  const team = await teamApi.listMembers({ user: { user_id: 'u1' } });
  assert.equal(team.available, true);
  assert.equal(team.members[0].role, 'owner');
  assert.equal(team.members[0].isCurrentUser, true);
  assert.equal(team.members[0].status, 'active');

  assert.equal((await teamApi.inviteMember({ email: 'new@example.com', role: 'staff' })).sent, true);
  assert.equal((await securityApi.changePassword({ currentPassword: 'old', newPassword: 'new' })).changed, true);

  // Genuinely, structurally unable to ever return real sessions (stateless
  // JWTs, no server-side session table) - available stays false so the UI
  // shows "not available", not a misleading "no sessions right now".
  assert.equal((await securityApi.getSessions()).available, false);

  const notifications = await preferencesApi.getNotificationPreferences();
  assert.equal(notifications.preferences.in_app.stock, false);
  assert.equal(notifications.preferences.email_frequency, 'daily');
  assert.equal(notifications.emailVerified, true);
  assert.equal(notifications.emailDeliveryAvailable, false);
  const saved = await preferencesApi.updateNotificationPreferences({ email: { pricing: false } });
  assert.equal(saved.preferences.email.pricing, false);
  assert.equal(saved.emailVerified, false);
  assert.deepEqual(NOTIFICATION_GROUPS, ['stock', 'pricing', 'market', 'data', 'billing']);
});
