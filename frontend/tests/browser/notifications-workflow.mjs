import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright-core';

const state = process.env.KEEL_VERIFICATION_STATE;
if (!state) throw new Error('Set KEEL_VERIFICATION_STATE to the reusable synthetic fixture directory.');
const fixture = JSON.parse(await readFile(`${state}/import-browser-fixture.json`, 'utf8'));
const alertFixture = JSON.parse(await readFile(`${state}/notification-browser-fixture.json`, 'utf8'));
const api = process.env.API_URL || 'http://127.0.0.1:8000';
const base = process.env.APP_URL || 'http://127.0.0.1:5178';
const locale = process.env.E2E_LOCALE || 'en';
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});

try {
  const page = await browser.newPage({ viewport: { width: locale === 'ar' ? 390 : 1365, height: 900 } });
  await page.addInitScript((language) => localStorage.setItem('ceopro_locale', language), locale);
  await page.goto(`${base}/login`);
  await page.locator('input[type="email"]').fill(fixture.email);
  await page.locator('input[type="password"]').fill(fixture.password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
  const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session') || '{}').accessToken);
  assert.ok(token, 'login must establish a backend-issued tenant session');
  const ownerHeaders = { Authorization: `Bearer ${token}` };

  const ownResponse = await page.request.get(`${api}/alerts`, { headers: ownerHeaders });
  assert.equal(ownResponse.status(), 200);
  const ownAlerts = await ownResponse.json();
  const persistedSignal = ownAlerts.alerts.find((item) => item.kind === 'import_failed' && item.params.name === alertFixture.file_name);
  assert.ok(persistedSignal, 'alert must be derived from the actual persisted failed-ingestion row');
  assert.ok(persistedSignal.unread, 'new signal must be unread for this user');

  const otherHeaders = { Authorization: `Bearer ${fixture.other_token}` };
  const otherResponse = await page.request.get(`${api}/alerts`, { headers: otherHeaders });
  assert.equal(otherResponse.status(), 200);
  assert.ok(!(await otherResponse.json()).alerts.some((item) => item.params?.name === alertFixture.file_name), 'another tenant must not see the source row');

  await page.locator('.apex-alerts__button').click();
  await page.getByRole('dialog', { name: locale === 'ar' ? 'التنبيهات' : 'Alerts' }).getByText(alertFixture.file_name, { exact: false }).waitFor({ timeout: 15000 });

  const readResponse = await page.request.post(`${api}/alerts/read`, { headers: ownerHeaders });
  assert.equal(readResponse.status(), 200);
  const afterRead = await (await page.request.get(`${api}/alerts`, { headers: ownerHeaders })).json();
  assert.equal(afterRead.unread, 0, 'read cursor must persist in PostgreSQL');
  await page.reload();
  await page.locator('.apex-alerts__button').waitFor();
  const afterRefresh = await (await page.request.get(`${api}/alerts`, { headers: ownerHeaders })).json();
  assert.equal(afterRefresh.unread, 0, 'read state must survive a full browser refresh');
  assert.equal(await page.locator('html').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');
  assert.ok(afterRefresh.alerts.some((item) => item.params.name === alertFixture.file_name), 'the source alert remains available after refreshing');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  assert.ok(overflow <= 1, `unexpected horizontal overflow: ${overflow}px`);
  console.log(`PASS: ${locale} authenticated alerts flow: API-backed failed-import alert, tenant isolation, persisted read state after refresh, RTL/layout.`);
} finally {
  await browser.close();
}
