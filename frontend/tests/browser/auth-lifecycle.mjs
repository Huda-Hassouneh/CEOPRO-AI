// Real React -> FastAPI -> PostgreSQL/Redis/SMTP. No intercepted API responses.
import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';
import { createHmac, randomUUID } from 'node:crypto';

const base = process.env.PHASE1A_BROWSER_BASE_URL;
if (process.env.PHASE1A_ISOLATED_BROWSER !== 'YES' || base !== 'http://127.0.0.1:15173') throw new Error('Disposable auth harness required');
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH, headless: true });
const page = await browser.newPage();
const failedResponses = [];
page.on('response', (response) => {
  if (response.status() >= 400) {
    response.json().then((body) => {
      const detail = typeof body?.detail === 'string' ? body.detail : body?.detail?.reason;
      failedResponses.push(`${response.status()} ${new URL(response.url()).pathname}${detail ? `: ${detail}` : ''}`);
    }).catch(() => failedResponses.push(`${response.status()} ${new URL(response.url()).pathname}`));
  }
});
page.setDefaultTimeout(15000);
const email = `auth-browser-${randomUUID()}@example.test`;
const password = `Auth-${randomUUID()}!aA9`;
let passed = 0;
const pass = (name) => { passed++; console.log(`PASS ${name}`); };
const mail = async (address) => {
  const response = await fetch(`http://127.0.0.1:18002/?email=${encodeURIComponent(address)}`, { headers: { 'X-Test-Key': process.env.AUTH_TEST_MAILBOX_KEY } });
  assert.equal(response.status, 200);
  return response.json();
};
const session = () => page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session')));
const api = (path, body, token, method = 'POST') => page.request.fetch(`${base}/api${path}`, {
  method, ...(body ? { data: body } : {}), headers: token ? { Authorization: `Bearer ${token}` } : {},
});
const fillCode = async (code) => {
  assert.match(code, /^\d{6}$/);
  for (let i = 0; i < 6; i++) await page.locator('input[inputmode="numeric"]').nth(i).fill(code[i]);
  await page.locator('button[type="submit"]').click();
};
const login = async (secret) => {
  if (new URL(page.url()).pathname !== '/login') await page.goto(`${base}/login`);
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(secret);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/dashboard');
};
const loginAs = async (address, secret) => {
  await page.goto(`${base}/login`);
  await page.locator('input[type="email"]').fill(address);
  await page.locator('input[type="password"]').fill(secret);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/dashboard');
};
const jwtClaims = (token) => JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString('utf8'));
const signedToken = (claims) => {
  const encode = (value) => Buffer.from(JSON.stringify(value)).toString('base64url');
  const unsigned = `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode(claims)}`;
  const signature = createHmac('sha256', process.env.JWT_SECRET).update(unsigned).digest('base64url');
  return `${unsigned}.${signature}`;
};
try {
  await page.goto(`${base}/signup`);
  await page.locator('input[autocomplete="name"]').fill('Browser Owner');
  await page.locator('input[autocomplete="organization"]').fill('Browser Auth Workspace');
  await page.locator('input[type="email"]').fill(email);
  await page.locator('select').nth(0).selectOption('JO');
  await page.locator('select').nth(1).selectOption('JOD');
  await page.locator('input[type="password"]').nth(0).fill(password);
  await page.locator('input[type="password"]').nth(1).fill(password);
  await page.locator('input[type="checkbox"]').check();
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/verify-email');
  const pending = await mail(email);
  assert.equal(pending.users, 0);
  pass('React signup persists pending registration without canonical user');
  await fillCode(pending.message.match(/code is: (\d{6})/)[1]);
  await page.waitForURL('**/dashboard');
  assert.equal((await mail(email)).users, 1);
  const original = await session();
  assert.ok(original.accessToken && original.tenantId);
  pass('SMTP verification provisions exactly one user and enters workspace');
  await page.reload();
  await page.waitForURL('**/dashboard');
  assert.equal((await api('/auth/workspaces', null, original.accessToken, 'GET')).status(), 200);
  pass('session restoration and authenticated workspace lookup');
  assert.equal((await api('/platform/me', null, original.accessToken, 'GET')).status(), 403);
  assert.equal((await api('/auth/workspaces/switch', { tenant_id: randomUUID() }, original.accessToken)).status(), 403);
  pass('ordinary owner denied platform and guessed tenant access');
  assert.equal((await api('/auth/refresh', null, original.accessToken)).status(), 200);
  pass('real token renewal');
  // Log out through the same production action used by the navigation menu.
  await page.evaluate(async () => {
    const { signOut } = await import('/src/shared/components/layout/signOut.js');
    const { useAuthStore } = await import('/src/features/auth/store/authStore.js');
    await signOut(useAuthStore.getState().clearSession, (path) => { location.href = path; });
  });
  await page.waitForURL('**/login');
  await page.locator('input[type="email"]').waitFor();
  assert.equal((await api('/auth/workspaces', null, original.accessToken, 'GET')).status(), 401);
  pass('frontend logout durably revokes old session');
  await login(password);
  const beforeReset = await session();
  await page.goto(`${base}/forgot-password`);
  await page.locator('input[type="email"]').fill(email);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/verify-code');
  const resetCode = (await mail(email)).message.match(/code is: (\d{6})/)[1];
  await fillCode(resetCode);
  await page.waitForURL('**/reset-password');
  const newPassword = `Reset-${randomUUID()}!aA9`;
  await page.locator('input[type="password"]').nth(0).fill(newPassword);
  await page.locator('input[type="password"]').nth(1).fill(newPassword);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/login');
  assert.equal((await api('/auth/workspaces', null, beforeReset.accessToken, 'GET')).status(), 401);
  assert.equal((await api('/auth/password/reset', { email, code: resetCode, new_password: password })).status(), 400);
  pass('SMTP password recovery changes password, invalidates session and rejects reuse');
  await login(newPassword);
  pass('login with recovered password');
  const owner = await session();
  const invitee = `auth-browser-${randomUUID()}@example.test`;
  await page.goto(`${base}/settings/team`);
  await page.getByRole('button', { name: /Invite member/i }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.locator('input[type="email"]').fill(invitee);
  await dialog.getByRole('button', { name: /Send invitation/i }).click();
  await dialog.waitFor({ state: 'hidden' });
  const invitation = (await mail(invitee)).message.match(/http:\/\/127\.0\.0\.1:15173\/invitation\/[^\s]+/)[0];
  pass('owner sends real invitation through team settings and SMTP');
  await page.goto(invitation);
  await page.locator('input[autocomplete="name"]').fill('Browser Member');
  await page.locator('input[type="password"]').fill(password);
  await page.getByRole('button', { name: 'Accept Invitation', exact: true }).click();
  await page.waitForURL('**/dashboard');
  const member = await session();
  assert.equal(member.tenantId, owner.tenantId);
  assert.deepEqual(member.roles, ['staff']);
  assert.equal((await mail(invitee)).users, 1);
  pass('emailed path token creates new invitee and establishes tenant session');
  assert.equal((await api('/settings/team/invitations', { email, role_key: 'admin' }, member.accessToken)).status(), 403);
  assert.equal((await api(`/auth/invitations/${invitation.split('/').at(-1)}/accept`, {}, null)).status(), 404);
  pass('member cannot invite and consumed invitation cannot be reused');
  const membershipResponse = await api('/settings/team/members', null, owner.accessToken, 'GET');
  const membership = (await membershipResponse.json()).members.find((row) => row.user_id === member.user.id);
  assert.ok(membership?.tenant_user_id);
  assert.equal((await api(`/settings/team/members/${membership.tenant_user_id}`, null, owner.accessToken, 'DELETE')).status(), 200);
  assert.equal((await api('/auth/workspaces', null, member.accessToken, 'GET')).status(), 403);
  pass('removed membership rejects stale access token');
  for (const locale of ['en', 'ar']) {
    await api('/auth/logout', {}, member.accessToken);
    await page.goto(`${base}/login`);
    await page.evaluate(() => { localStorage.removeItem('ceopro_auth_session'); localStorage.removeItem('ceopro_session'); localStorage.removeItem('ceopro_token'); });
    await page.evaluate((value) => localStorage.setItem('ceopro_locale', value), locale);
    await page.reload();
    await page.goto(`${base}/signup`);
    assert.equal(await page.locator('html').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.locator('input[type="email"]').isVisible());
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    pass(`${locale} responsive signup form and document direction`);
  }
  await page.goto(`${base}/login`);
  await page.evaluate(() => localStorage.setItem('ceopro_locale', 'en'));
  await page.reload();
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(newPassword);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/dashboard');
  const beforeChange = await session();
  await page.goto(`${base}/settings?tab=security`);
  await page.locator('input[autocomplete="current-password"]').fill(newPassword);
  const changedPassword = `Changed-${randomUUID()}!aA9`;
  await page.locator('input[autocomplete="new-password"]').nth(0).fill(changedPassword);
  await page.locator('input[autocomplete="new-password"]').nth(1).fill(changedPassword);
  await page.getByRole('button', { name: /Change password/i }).click();
  await page.waitForURL('**/login');
  assert.equal((await api('/auth/workspaces', null, beforeChange.accessToken, 'GET')).status(), 401);
  await login(changedPassword);
  pass('authenticated password change rotates credential version and rejects prior session');

  // Create a second fully initialized workspace through the existing UI and
  // onboarding APIs, without bypassing their membership or entitlement gates.
  const firstWorkspace = await session();
  await page.goto(`${base}/workspaces/new`);
  await page.locator('.workspace-create input').fill('Browser Secondary Workspace');
  await page.locator('.workspace-create select').nth(0).selectOption('JO');
  await page.locator('.workspace-create select').nth(1).selectOption('JOD');
  await page.locator('.workspace-create button[type="submit"]').click();
  // Dashboard renders first; SetupGate performs the real profile read before
  // redirecting. Wait for that gate rather than mistaking the initial route
  // transition for completed setup.
  await page.waitForURL('**/onboarding');
  await page.getByRole('radio').first().click();
  await page.locator('.setup-actions button').first().click();
  await page.locator('.setup-steps li[aria-current="step"]:nth-child(2)').waitFor();
  await page.locator('.setup-field input').first().fill('Amman');
  await page.locator('.setup-actions button').last().click();
  await page.locator('.setup-steps li[aria-current="step"]:nth-child(3)').waitFor();
  await page.locator('.setup-actions button').last().click();
  await page.locator('.setup-steps li[aria-current="step"]:nth-child(4)').waitFor();
  await page.locator('.setup-actions button').nth(1).click();
  await page.waitForURL('**/dashboard');
  const secondWorkspace = await session();
  assert.notEqual(firstWorkspace.tenantId, secondWorkspace.tenantId);
  assert.equal(jwtClaims(secondWorkspace.accessToken).ev, true, 'workspace creation must preserve verified email state');
  const initializedCompany = await api('/settings/company', null, secondWorkspace.accessToken, 'GET');
  assert.equal(initializedCompany.status(), 200);
  assert.ok((await initializedCompany.json()).onboarding_completed_at);
  const workspaceList = await (await api('/auth/workspaces', null, secondWorkspace.accessToken, 'GET')).json();
  assert.equal(workspaceList.workspaces.length, 2);
  assert.ok(workspaceList.workspaces.every((item) => item.business_name));
  pass('second workspace is created and fully initialized through existing onboarding');

  // Login without tenant_id must present the actual server-approved choices.
  await page.evaluate(async () => {
    const { signOut } = await import('/src/shared/components/layout/signOut.js');
    const { useAuthStore } = await import('/src/features/auth/store/authStore.js');
    await signOut(useAuthStore.getState().clearSession, (path) => { location.href = path; });
  });
  await page.waitForURL('**/login');
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(changedPassword);
  await page.locator('button[type="submit"]').click();
  await page.getByRole('heading', { name: /choose a company/i }).waitFor();
  const intended = page.getByRole('button', { name: /Browser Secondary Workspace/ });
  await intended.click();
  await page.waitForURL('**/dashboard');
  assert.equal((await session()).tenantId, secondWorkspace.tenantId);
  pass('multi-workspace login lists active workspaces and opens the selected tenant');

  const beforeSwitch = await session();
  const authTime = jwtClaims(beforeSwitch.accessToken).auth_time;
  await page.locator('button[aria-haspopup="menu"]').first().click();
  await page.getByRole('menuitemradio', { name: /Browser Auth Workspace/ }).click();
  await page.waitForFunction((tenantId) => JSON.parse(localStorage.getItem('ceopro_auth_session'))?.tenantId === tenantId, firstWorkspace.tenantId);
  const afterSwitch = await session();
  assert.equal(afterSwitch.tenantId, firstWorkspace.tenantId);
  assert.equal(jwtClaims(afterSwitch.accessToken).auth_time, authTime);
  assert.equal((await api('/auth/workspaces', null, afterSwitch.accessToken, 'GET')).status(), 200);
  assert.equal((await api('/auth/workspaces/switch', { tenant_id: randomUUID() }, afterSwitch.accessToken)).status(), 403);
  const renewed = await api('/auth/refresh', null, afterSwitch.accessToken);
  assert.equal(renewed.status(), 200);
  assert.equal(jwtClaims((await renewed.json()).access_token).auth_time, authTime);
  pass('workspace switch changes tenant context, rejects guessed IDs, and preserves auth_time through renewal');

  // Deterministic boundary tests: a valid signed expired token exercises the
  // browser 401 route, while an over-age auth_time exercises the server's
  // maximum-lifetime renewal guard without sleeping.
  const activeClaims = jwtClaims(afterSwitch.accessToken);
  const expiryNow = Math.floor(Date.now() / 1000);
  const oldAuth = signedToken({ ...activeClaims, exp: expiryNow + 600, iat: expiryNow, auth_time: expiryNow - (168 * 3600) - 1, jti: randomUUID() });
  assert.equal((await api('/auth/refresh', null, oldAuth)).status(), 401);
  const expired = signedToken({ ...activeClaims, exp: expiryNow - 1, iat: expiryNow - 7200, jti: randomUUID() });
  await page.evaluate((token) => {
    const saved = JSON.parse(localStorage.getItem('ceopro_auth_session'));
    localStorage.setItem('ceopro_auth_session', JSON.stringify({ ...saved, accessToken: token }));
  }, expired);
  await page.goto(`${base}/settings/team`);
  await page.waitForURL('**/login');
  await page.getByRole('alert').filter({ hasText: /session has expired/i }).waitFor();
  pass('maximum session age is enforced and expired-session UX explains the sign-in redirect');

  // Platform invitation acceptance uses the existing one-time owner bootstrap,
  // real platform APIs, controlled SMTP, and the actual React invitation page.
  const platformEmail = process.env.AUTH_BROWSER_PLATFORM_OWNER_EMAIL;
  const platformPassword = process.env.AUTH_BROWSER_PLATFORM_OWNER_PASSWORD;
  assert.ok(platformEmail && platformPassword);
  await loginAs(platformEmail, platformPassword);
  await page.goto(`${base}/platform`);
  await page.locator('main.keel-platform').waitFor();
  await page.getByRole('button', { name: /operators/i }).click();
  await page.getByRole('button', { name: /invite/i }).click();
  const platformInvitee = `auth-browser-${randomUUID()}@example.test`;
  const platformForm = page.locator('form.platform-editor');
  await platformForm.locator('input[type="email"]').fill(platformInvitee);
  await platformForm.locator('input').nth(1).fill('Browser acceptance invitation');
  await platformForm.getByRole('button', { name: /confirm/i }).click();
  await page.waitForFunction((address) => document.body.innerText.includes(address), platformInvitee);
  const platformMessage = (await mail(platformInvitee)).message;
  const platformLink = platformMessage.match(/http:\/\/127\.0\.0\.1:15173\/platform\/invitations\/[^\s]+/)[0];
  await page.goto(platformLink);
  await page.locator('input[autocomplete="name"]').fill('Browser Platform Admin');
  const platformAdminPassword = `Admin-${randomUUID()}!aA9`;
  await page.locator('input[autocomplete="new-password"]').fill(platformAdminPassword);
  await page.getByRole('button', { name: /accept.*invitation/i }).click();
  await page.waitForURL('**/platform');
  const platformAdmin = await session();
  const platformWho = await (await api('/platform/me', null, platformAdmin.accessToken, 'GET')).json();
  assert.equal(platformWho.role, 'admin');
  await page.goto(`${base}/platform`);
  await page.getByRole('button', { name: /operators/i }).click();
  assert.equal(await page.getByRole('button', { name: /transfer platform ownership/i }).count(), 0);
  assert.equal(await page.getByRole('button', { name: /remove operator/i }).count(), 0);
  assert.equal(await page.getByRole('button', { name: /^exceptional approvals$/i }).count(), 0);
  pass('Platform Admin sees operational team view without Owner-only controls');
  const ownerOnly = await api('/platform/financial-approvals', {
    request_id: randomUUID(), kind: 'manual_access', subject: 'auth-browser-check',
    terms: { description: 'not an owner approval' },
    expires_at: new Date(Date.now() + 3600000).toISOString(), reason: 'verify admin boundary',
  }, platformAdmin.accessToken);
  assert.equal(ownerOnly.status(), 403);
  const acceptedReplay = await api(`/platform/invitations/${platformLink.split('/').at(-1)}/accept`, {}, null);
  assert.equal(acceptedReplay.status(), 404);
  await page.goto(platformLink);
  await page.getByRole('alert').waitFor();
  pass('platform owner invitation is emailed, accepted once, and creates only the approved admin role');

  const tenantInviteDenied = await api('/platform/team/invitations', { email: `auth-browser-${randomUUID()}@example.test`, reason: 'tenant owner must not invite platform staff' }, firstWorkspace.accessToken);
  assert.equal(tenantInviteDenied.status(), 403);
  await page.evaluate(async () => {
    const { signOut } = await import('/src/shared/components/layout/signOut.js');
    const { useAuthStore } = await import('/src/features/auth/store/authStore.js');
    await signOut(useAuthStore.getState().clearSession, (path) => { location.href = path; });
  });
  await page.waitForURL('**/login');
  await loginAs(platformEmail, platformPassword);
  await page.goto(`${base}/platform`);
  await page.getByRole('button', { name: /operators/i }).click();
  await page.getByRole('button', { name: /invite/i }).click();
  const expiredInvitee = `auth-browser-${randomUUID()}@example.test`;
  const expiredForm = page.locator('form.platform-editor');
  await expiredForm.locator('input[type="email"]').fill(expiredInvitee);
  await expiredForm.locator('input').nth(1).fill('Expired invitation acceptance test');
  await expiredForm.getByRole('button', { name: /confirm/i }).click();
  await page.waitForFunction((address) => document.body.innerText.includes(address), expiredInvitee);
  const expiredLink = (await mail(expiredInvitee)).message.match(/http:\/\/127\.0\.0\.1:15173\/platform\/invitations\/[^\s]+/)[0];
  const expireResponse = await fetch(`http://127.0.0.1:18002/expire-platform-invitation?email=${encodeURIComponent(expiredInvitee)}`, {
    method: 'POST', headers: { 'X-Test-Key': process.env.AUTH_TEST_MAILBOX_KEY },
  });
  assert.equal((await expireResponse.json()).expired, true);
  await page.evaluate(() => localStorage.setItem('ceopro_locale', 'ar'));
  await page.goto(expiredLink);
  await page.waitForFunction(() => document.documentElement.dir === 'rtl');
  const expiredAlert = page.getByRole('alert');
  await expiredAlert.waitFor();
  assert.ok((await expiredAlert.textContent()).trim().length > 0);
  assert.equal((await api(`/platform/invitations/${expiredLink.split('/').at(-1)}`, null, null, 'GET')).status(), 404);
  pass('tenant owners cannot send platform invitations; expired/reused links fail with localized RTL feedback');

  // The authenticated Platform Admin view searches a populated disposable
  // directory. Matching records span three pages, proving the server filters
  // the full directory before it paginates.
  await page.evaluate(() => localStorage.setItem('ceopro_locale', 'en'));
  await page.goto(`${base}/platform`);
  await page.locator('main.keel-platform').waitFor();
  await page.locator('nav[aria-label] button').nth(1).click();
  const searchMarker = process.env.AUTH_BROWSER_PLATFORM_SEARCH_MARKER;
  assert.ok(searchMarker);
  const companySearch = page.getByLabel(/search all companies/i);
  await companySearch.waitFor();
  await companySearch.fill(searchMarker);
  await page.getByRole('status').filter({ hasText: 'Matching records: 120' }).waitFor();
  const companyRows = page.locator('table tbody tr');
  await page.waitForFunction(() => document.querySelectorAll('main.keel-platform table tbody tr').length === 50);
  assert.equal(await companyRows.count(), 50);
  assert.equal(await page.getByText(new RegExp(`Company 119`)).count(), 0);
  await page.getByRole('button', { name: /next/i }).click();
  await page.waitForFunction(() => document.querySelectorAll('main.keel-platform table tbody tr').length === 50);
  await page.getByRole('button', { name: /next/i }).click();
  await page.waitForFunction(() => document.querySelectorAll('main.keel-platform table tbody tr').length === 20);
  await page.getByText(new RegExp(`Company 119`)).waitFor();
  pass('Platform Admin company search finds a third-page record and paginates the 120-result filtered set');
  await companySearch.fill(`missing-${randomUUID()}`);
  await page.getByRole('status').filter({ hasText: /no matching records found/i }).waitFor();
  await page.getByRole('status').filter({ hasText: 'Matching records: 0' }).waitFor();
  await companySearch.fill(`${searchMarker} Company 119`);
  await page.getByRole('status').filter({ hasText: 'Matching records: 1' }).waitFor();
  assert.equal(await page.locator('table tbody tr').count(), 1);
  await page.getByRole('button', { name: /details/i }).click();
  await page.locator('main.keel-platform section h2').waitFor();
  pass('Platform Admin filtered count and company detail remain correct for a later-page match');

  // Switch to Users and search the same-size directory, then exercise Arabic
  // RTL rendering and a match that is only reached on the final filtered page.
  await page.locator('nav[aria-label] button').nth(2).click();
  const userSearch = page.getByLabel(/search all users/i);
  await userSearch.fill(searchMarker);
  await page.getByRole('status').filter({ hasText: 'Matching records: 120' }).waitFor();
  await page.waitForFunction(() => document.querySelectorAll('main.keel-platform table tbody tr').length === 50);
  await page.getByRole('button', { name: /next/i }).click();
  await page.waitForFunction(() => document.querySelectorAll('main.keel-platform table tbody tr').length === 50);
  await page.getByRole('button', { name: /next/i }).click();
  await page.waitForFunction(() => document.querySelectorAll('main.keel-platform table tbody tr').length === 20);
  await page.getByText(new RegExp(`User 119`)).waitFor();
  pass('Platform Admin user search reaches the third filtered page and preserves its total count');

  await page.evaluate(() => localStorage.setItem('ceopro_locale', 'ar'));
  await page.reload();
  await page.locator('main.keel-platform').waitFor();
  await page.waitForFunction(() => document.documentElement.dir === 'rtl');
  await page.locator('nav[aria-label] button').nth(1).click();
  const arabicCompanySearch = page.locator('main.keel-platform input').first();
  await arabicCompanySearch.waitFor();
  const arabicLabel = await arabicCompanySearch.evaluate((input) => input.labels?.[0]?.textContent || '');
  assert.ok(/[\u0600-\u06FF]/.test(arabicLabel));
  await arabicCompanySearch.fill(`${searchMarker} Company 119`);
  await page.waitForFunction(() => [...document.querySelectorAll('[role="status"]')]
    .some((node) => node.textContent?.trim().endsWith('1')));
  await page.getByText(new RegExp('Company 119')).waitFor();
  pass('Arabic RTL platform search reaches the same server-filtered company result');

  console.log(`AUTH BROWSER: ${passed} passed, 0 failed, 0 skipped (listed journeys only)`);
} catch (error) {
  console.error(`AUTH BROWSER: ${passed} passed before failure; ${error.message}`);
  console.error(`Page path: ${new URL(page.url()).pathname}`);
  console.error((await page.locator('[role="alert"]').allTextContents().catch(() => [])).join('\n'));
  console.error([...new Set(failedResponses)].slice(-12).join('\n'));
  const current = await session().catch(() => null);
  if (current?.accessToken) {
    const claims = jwtClaims(current.accessToken);
    const statuses = [];
    for (const [path, method] of [['/auth/workspaces', 'GET'], ['/settings/company', 'GET'], ['/settings/company/search-scope', 'GET'], ['/auth/refresh', 'POST']]) {
      const response = await api(path, null, current.accessToken, method).catch(() => null);
      statuses.push(`${path}=${response?.status() ?? 'network-error'}`);
    }
    console.error(`Current disposable session claims ev=${claims.ev} evr=${claims.evr} cv=${claims.cv}; ` + statuses.join(' '));
  }
  process.exitCode = 1;
} finally {
  await browser.close();
}
