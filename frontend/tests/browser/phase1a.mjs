// Real browser/API smoke. Requires an isolated migrated API/Redis/SMTP test stack.
// Reuses an explicitly supplied test-only session; never creates an owner implicitly.
import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';
const base = process.env.PHASE1A_BROWSER_BASE_URL;
if (!base || process.env.PHASE1A_ISOLATED_BROWSER !== 'YES') throw new Error('Explicit isolated browser stack required');
const parsed = new URL(base);
if (!['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname)) throw new Error('Refuse nonlocal Phase 1A browser target');
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
if (!executablePath) throw new Error('Supply the local browser executable');
const browser = await chromium.launch({ executablePath, headless: true });
try {
  const page = await browser.newPage();
  await page.goto(`${base}/platform`);
  await page.waitForURL('**/login');
  await assert.doesNotReject(() => page.locator('form').waitFor());
  await page.goto(`${base}/platform/invitations/invalid-test-invitation`);
  await page.getByRole('alert').waitFor();
  const token = process.env.PHASE1A_BROWSER_INVITATION_TOKEN;
  if (token) {
    // Token belongs solely to this disposable environment. Existing user invitation may be accepted without a password.
    await page.goto(`${base}/platform/invitations/${encodeURIComponent(token)}`);
    await page.getByRole('button', { name: /Accept platform invitation|قبول دعوة المنصة/ }).click();
    await page.waitForURL('**/platform');
    await page.getByRole('heading', { name: /Platform administration|إدارة المنصة/ }).waitFor();
    // A normal platform admin must never see exceptional owner approvals.
    await assert.equal(await page.getByRole('button', { name: /^Exceptional approvals$|^الموافقات الاستثنائية$/ }).count(), 0);
  } else {
    console.log('NOT RUN: accepted-invitation management journey (test invitation token not supplied)');
  }
} finally { await browser.close(); }
