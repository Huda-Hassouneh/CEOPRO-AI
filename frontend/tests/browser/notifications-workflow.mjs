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

  const ownResponse = await page.request.get(`${api}/notifications`, { headers: ownerHeaders });
  assert.equal(ownResponse.status(), 200);
  const inbox = await ownResponse.json();
  const persistedSignal = inbox.items.find((item) => item.event_kind === 'import_failed' && item.payload.params.name === alertFixture.file_name);
  assert.ok(persistedSignal, 'notification must be persisted from the failed-ingestion transition');
  assert.ok(!persistedSignal.read_at && !persistedSignal.dismissed_at, 'new notification must be unread and active');
  assert.equal(inbox.unread_count, 1);

  const derivedResponse = await page.request.get(`${api}/alerts`, { headers: ownerHeaders });
  assert.equal(derivedResponse.status(), 200);
  const derivedAlerts = await derivedResponse.json();
  assert.ok(!derivedAlerts.alerts.some((item) => item.kind === 'import_failed' && item.params.name === alertFixture.file_name),
    'the same event must not be delivered twice through Smart Alerts and the inbox');

  const otherHeaders = { Authorization: `Bearer ${fixture.other_token}` };
  const otherResponse = await page.request.get(`${api}/notifications`, { headers: otherHeaders });
  assert.equal(otherResponse.status(), 200);
  assert.ok(!(await otherResponse.json()).items.some((item) => item.payload?.params?.name === alertFixture.file_name), 'another tenant must not see the notification');

  await page.locator('.apex-alerts__button').click();
  const dialog = page.getByRole('dialog');
  await dialog.getByText(alertFixture.file_name, { exact: false }).waitFor({ timeout: 15000 });

  const readResponse = await page.request.post(`${api}/notifications/${persistedSignal.notification_id}/read`, { headers: ownerHeaders });
  assert.equal(readResponse.status(), 200);
  const afterRead = await (await page.request.get(`${api}/notifications`, { headers: ownerHeaders })).json();
  assert.equal(afterRead.unread_count, 0, 'recipient read state must persist in PostgreSQL');
  assert.ok(afterRead.items.find((item) => item.notification_id === persistedSignal.notification_id).read_at);

  const notificationRow = dialog.locator('li').filter({ hasText: alertFixture.file_name });
  const dismissButton = notificationRow.locator('button.apex-alerts__dismiss');
  assert.equal(await dismissButton.count(), 1, 'dismiss action is visible in the localized inbox');
  await dismissButton.click();
  await page.waitForTimeout(300);
  const afterDismiss = await (await page.request.get(`${api}/notifications`, { headers: ownerHeaders })).json();
  assert.equal(afterDismiss.total, 0, 'dismissal removes the row from the active inbox');
  const history = await (await page.request.get(`${api}/notifications?include_dismissed=true`, { headers: ownerHeaders })).json();
  assert.ok(history.items.some((item) => item.notification_id === persistedSignal.notification_id && item.dismissed_at), 'dismissed history remains available');

  await page.reload();
  await page.locator('.apex-alerts__button').waitFor();
  const afterRefresh = await (await page.request.get(`${api}/notifications?include_dismissed=true`, { headers: ownerHeaders })).json();
  assert.equal(afterRefresh.unread_count, 0, 'read state must survive a full browser refresh');
  assert.ok(afterRefresh.items.some((item) => item.notification_id === persistedSignal.notification_id && item.dismissed_at), 'notification history remains available after refresh');
  assert.equal(await page.locator('html').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  assert.ok(overflow <= 1, `unexpected horizontal overflow: ${overflow}px`);
  console.log(`PASS: ${locale} authenticated notifications flow: persisted inbox, Smart Alerts deduplication, tenant isolation, read/dismiss/history persistence, RTL/layout.`);
} finally {
  await browser.close();
}
