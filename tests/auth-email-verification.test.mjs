import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

test('signup targets the backend registration endpoint and maps the form fields', () => {
  const contracts = read('src/features/auth/api/authContracts.js');
  const adapter = read('src/features/auth/api/authHttpAdapter.js');
  const api = read('src/features/auth/api/authApi.js');
  assert.match(contracts, /signup:\s*'\/auth\/register'/);
  assert.match(adapter, /fullName:\s*payload\.fullName\s*\?\?\s*payload\.name/);
  assert.match(adapter, /businessName:\s*payload\.businessName\s*\?\?\s*payload\.business/);
  assert.match(api, /VITE_AUTH_API_MODE\s*===\s*AUTH_API_MODE\.MOCK[\s\S]*\?\s*AUTH_API_MODE\.MOCK[\s\S]*:\s*AUTH_API_MODE\.HTTP/);
});

test('verification exchange stores the session and sends the customer to onboarding', () => {
  const contracts = read('src/features/auth/api/authContracts.js');
  const adapter = read('src/features/auth/api/authHttpAdapter.js');
  const page = read('src/features/auth/pages/VerifyEmailPage.jsx');
  assert.match(contracts, /verifyEmail:\s*'\/auth\/verification\/exchange'/);
  assert.match(adapter, /verifyEmail:\s*\(payload\)\s*=>\s*unwrap\(httpClient\.post\(authEndpoints\.verifyEmail,\s*payload\)\)/);
  assert.match(page, /verifyMutation\.mutate\(\{ code \}\)/);
  assert.match(page, /setSession\(response\.session\)/);
  assert.match(page, /navigate\(routePaths\.onboardingWelcome,\s*\{ replace: true \}\)/);
});

test('email token opens frontend confirmation and posts only after the user submits', () => {
  const page = read('src/features/auth/pages/VerifyEmailPage.jsx');
  assert.match(page, /query\.get\('token'\)/);
  assert.match(page, /method="post" action=\{`\$\{apiBaseUrl\}\/auth\/verify-email\/confirm`\}/);
  assert.match(page, /name="token" value=\{token\}/);
  assert.match(page, /type="submit"/);
});
