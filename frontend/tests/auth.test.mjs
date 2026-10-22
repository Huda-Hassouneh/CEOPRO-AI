import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { authHttpAdapter } from '../src/features/auth/api/authHttpAdapter.js';
import httpClient from '../src/shared/lib/httpClient.js';

test('password recovery and invitation adapters preserve the actual Python contracts', async (t) => {
  const received = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      received.push({ path: req.url, body: body ? JSON.parse(body) : null });
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify(req.url.endsWith('/accept')
        ? { access_token: 'test-token', tenant_id: 'tenant', user_id: 'member', role_key: 'staff' }
        : req.method === 'GET' ? { email: 'member@example.test', business_name: 'Workspace', role_name: 'Staff' } : { ok: true }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const previous = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = previous; server.close(); });
  await authHttpAdapter.resetPassword({ email: 'member@example.test', code: '123456', password: 'NewPassword1!', confirmPassword: 'NewPassword1!' });
  assert.deepEqual(received[0].body, { email: 'member@example.test', code: '123456', new_password: 'NewPassword1!' });
  const invitation = await authHttpAdapter.getInvitation('invite-token');
  assert.equal(invitation.invitation.organizationName, 'Workspace');
  assert.equal(invitation.invitation.roleName, 'Staff');
  const accepted = await authHttpAdapter.acceptInvitation({ token: 'invite-token', full_name: 'Member', password: 'NewPassword1!' });
  assert.equal(accepted.session.tenantId, 'tenant');
  assert.deepEqual(accepted.session.roles, ['staff']);
  assert.deepEqual(received[2].body, { full_name: 'Member', password: 'NewPassword1!' });
  assert.equal(received[2].path, '/auth/invitations/invite-token/accept');
});

// SignupPage's local form state ({name, business, email, password,
// confirmPassword, acceptedTerms, country, currency}) never matched the
// backend's real SignupRequest ({email, password, full_name, business_name,
// country_code, primary_currency}) - authHttpAdapter.signup passed the raw
// form payload straight through, so every real signup 422'd server-side
// (missing full_name/business_name/country_code/primary_currency entirely).
// This locks in the real translation so it can't silently regress back to
// a pass-through.
test('signup translates the real signup form shape into the real backend SignupRequest shape', async (t) => {
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      res.setHeader('Content-Type', 'application/json');
      const parsed = JSON.parse(body);
      if (req.url === '/auth/signup' && req.method === 'POST') {
        assert.deepEqual(parsed, {
          email: 'jane@example.com',
          password: 'Secret123!',
          full_name: 'Jane Doe',
          business_name: 'Acme Corp',
          country_code: 'JO',
          primary_currency: 'JOD',
        });
        // confirmPassword/acceptedTerms must never reach the backend.
        assert.equal('confirmPassword' in parsed, false);
        assert.equal('acceptedTerms' in parsed, false);
        return res.end(JSON.stringify({
          access_token: 'tok', token_type: 'bearer', tenant_id: 't1', user_id: 'u1',
          role_key: 'owner', business_name: 'Acme Corp', full_name: 'Jane Doe', preferred_language: 'en',
        }));
      }
      res.statusCode = 404;
      res.end(JSON.stringify({ detail: 'not found' }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const result = await authHttpAdapter.signup({
    name: 'Jane Doe',
    business: 'Acme Corp',
    email: 'jane@example.com',
    password: 'Secret123!',
    confirmPassword: 'Secret123!',
    country: 'JO',
    currency: 'JOD',
    acceptedTerms: true,
  });

  assert.equal(result.session.accessToken, 'tok');
  assert.equal(result.session.roles[0], 'owner');
  assert.equal(result.session.user.fullName, 'Jane Doe');
});
