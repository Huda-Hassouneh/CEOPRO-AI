import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { authHttpAdapter } from '../src/features/auth/api/authHttpAdapter.js';
import httpClient from '../src/shared/lib/httpClient.js';

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
