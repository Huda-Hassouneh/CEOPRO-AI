import { chromium } from '../../tmp/visual-qa/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage(); page.setDefaultTimeout(10000);
const errors = []; page.on('pageerror', error => errors.push(error.message));
fs.mkdirSync('tmp/admin-screens', { recursive: true });
const settle = async () => { await page.waitForTimeout(650); await page.locator('.pa-loading').waitFor({ state: 'hidden' }); };
const go = async path => { await page.evaluate(path => { history.pushState({ idx: (history.state?.idx || 0) + 1 }, '', '/admin' + path); dispatchEvent(new PopStateEvent('popstate', { state: history.state })); }, path); await settle(); };
const overflow = async label => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Overflow: ${label}`);
await page.goto('http://127.0.0.1:5182/admin');
await page.getByRole('button', { name: 'Super Admin', exact: true }).click(); await settle();
await page.getByRole('heading', { name: 'Platform Overview', exact: true }).waitFor();
assert.equal(await page.locator('.pa-kpi').count(), 4);
await page.screenshot({ path: 'tmp/admin-screens/overview-en.png', fullPage: true });
for (const [path, title] of [['/companies', 'Companies'], ['/users', 'Users'], ['/subscriptions', 'Subscriptions'], ['/plans', 'Plans & Pricing'], ['/features', 'Features & Limits'], ['/admin-team', 'Admin Team'], ['/audit-logs', 'Audit Logs'], ['/settings', 'Platform Settings'], ['/profile', 'Profile'], ['/security', 'Security']]) {
  await go(path); await page.getByRole('heading', { name: title, exact: true, level: 1 }).waitFor(); await overflow(path);
}
console.log('All admin sections rendered.');
await go('/companies');
await page.getByRole('button', { name: 'Company', exact: true }).click(); await settle(); assert.match(page.url(), /sort=name/); assert.match(page.url(), /direction=asc/);
await page.getByRole('searchbox', { name: 'Search records' }).fill('no-such-record'); await settle(); await page.getByText('No records match these filters.').waitFor();
await page.getByRole('button', { name: 'Clear filters' }).click(); await settle();
await page.getByRole('button', { name: 'Next', exact: true }).click(); await settle(); assert.match(page.url(), /page=2/); assert.equal(await page.locator('tbody tr').count(), 4);
await go('/companies/company-1');
for (const tab of ['Subscription', 'Users', 'Usage', 'Business data summary', 'Administrative activity', 'Overview']) { await page.getByRole('tab', { name: tab, exact: true }).click(); await settle(); }
await page.getByRole('button', { name: 'Suspend access', exact: true }).click();
await page.getByRole('button', { name: 'Cancel', exact: true }).focus(); await page.keyboard.press('Tab'); assert.equal(await page.evaluate(() => !!document.activeElement.closest('[role=dialog]')), true);
await page.keyboard.press('Escape'); assert.equal(await page.getByRole('dialog').count(), 0);
await page.getByRole('button', { name: 'Edit administrative notes' }).click(); await page.getByRole('textbox', { name: 'Internal administrative notes' }).fill('Operational review complete.'); await page.getByRole('button', { name: 'Confirm changes' }).click(); await settle(); await page.getByText('Operational review complete.', { exact: true }).waitFor();
await go('/users/user-1'); await page.getByRole('button', { name: 'Suspend access' }).click(); await page.getByRole('button', { name: 'Confirm changes' }).click(); await settle(); await page.getByRole('button', { name: 'Activate access' }).waitFor();
await go('/subscriptions/subscription-1'); await page.getByRole('button', { name: 'Cancel subscription' }).click(); await page.getByRole('button', { name: 'Confirm changes' }).click(); await settle(); assert.equal(await page.getByRole('button', { name: 'Cancel subscription' }).count(), 0);
console.log('Tables, scoped detail tabs and operational confirmations passed.');
await go('/plans/pro/edit'); await page.getByRole('tab', { name: 'Pricing & billing' }).click(); await page.getByRole('spinbutton', { name: 'Monthly price', exact: true }).fill('109');
await page.locator('.pa-sidebar a[href="/admin/companies"]').click(); await page.getByRole('dialog', { name: 'Unsaved changes' }).waitFor(); await page.getByRole('button', { name: 'Keep editing' }).click();
await page.getByRole('tab', { name: 'Feature availability', exact: true }).click(); await page.getByLabel('Market Intelligence', { exact: true }).selectOption('true');
await page.getByRole('button', { name: 'Review changes', exact: true }).click(); await page.getByRole('dialog').getByText('109', { exact: true }).waitFor(); await page.getByRole('button', { name: 'Confirm changes' }).click(); await settle();
assert.equal(await page.getByRole('button', { name: 'Review changes', exact: true }).isDisabled(), true);
await go('/features'); assert.ok(await page.locator('tbody tr').first().getByText('Enabled', { exact: true }).count() > 0);
await go('/plans'); await page.screenshot({ path: 'tmp/admin-screens/plans-en.png', fullPage: true }); await page.getByText('$109', { exact: true }).waitFor();
// Public pricing uses the same in-memory catalog, without touching customer data.
await page.evaluate(() => { history.pushState({ idx: (history.state?.idx || 0) + 1 }, '', '/'); dispatchEvent(new PopStateEvent('popstate', { state: history.state })); }); await page.waitForTimeout(450);
await page.locator('.ceopro-plan-card').first().waitFor(); assert.ok((await page.locator('.ceopro-plan-card').allTextContents()).some(text => text.includes('109')));
await go('/admin-team');
await page.getByRole('row').filter({ hasText: 'alex@example.test' }).getByRole('button', { name: 'Manage access' }).click(); await page.getByRole('dialog').getByLabel('Action', { exact: true }).selectOption('remove'); await page.getByRole('button', { name: 'Confirm changes' }).click(); await page.getByText('Another active Super Admin is required', { exact: false }).waitFor(); await page.getByRole('button', { name: 'Cancel', exact: true }).click();
await page.getByRole('button', { name: 'Invite admin member' }).click(); await page.getByLabel('Email', { exact: true }).fill('browser-test@example.test'); await page.getByRole('button', { name: 'Send invitation' }).click(); await settle();
await page.getByRole('searchbox').fill('browser-test'); await settle(); await page.getByText('browser-test@example.test', { exact: true }).waitFor();
await page.getByRole('button', { name: 'Invite admin member' }).click(); await page.getByLabel('Email', { exact: true }).fill('browser-test@example.test'); await page.getByRole('button', { name: 'Send invitation' }).click(); await page.getByText('This email already has access or a pending invitation.').waitFor(); await page.getByRole('button', { name: 'Cancel', exact: true }).click();
await go('/admin-team'); await page.getByRole('row').filter({ hasText: 'sam@example.test' }).getByRole('button', { name: 'Manage access' }).click(); await page.getByLabel('New role', { exact: true }).selectOption('VIEWER'); await page.getByRole('button', { name: 'Confirm changes' }).click(); await settle(); await page.getByRole('row').filter({ hasText: 'sam@example.test' }).getByText('Viewer', { exact: true }).waitFor();
await go('/audit-logs'); assert.ok(await page.locator('tbody tr').count() > 0); await page.getByRole('combobox', { name: 'Action', exact: true }).selectOption('planUpdated'); await settle(); assert.equal(await page.locator('tbody tr').count(), 1); await page.getByRole('button', { name: 'View details' }).click(); await page.getByRole('dialog').getByText('109', { exact: true }).waitFor(); await page.keyboard.press('Escape');
await go('/settings'); await page.getByLabel('Platform display name').fill('CEOPRO Operations'); await page.getByRole('button', { name: 'Review changes' }).click(); await page.getByRole('button', { name: 'Confirm changes' }).click(); await settle(); assert.equal(await page.getByRole('button', { name: 'Review changes' }).isDisabled(), true);
await go('/security'); await page.getByLabel('Current password', { exact: true }).fill('current-password-test'); await page.getByLabel('New password', { exact: true }).fill('new-password-test-123'); await page.getByLabel('Confirm new password', { exact: true }).fill('new-password-test-123'); await page.getByRole('button', { name: 'Change password', exact: true }).click(); await page.getByRole('button', { name: 'Confirm changes' }).click(); await settle(); assert.equal(await page.getByLabel('Current password', { exact: true }).inputValue(), '');
await page.getByRole('button', { name: 'Sign out all other sessions' }).click(); await page.getByRole('button', { name: 'Confirm changes' }).click(); await settle(); assert.equal(await page.locator('.pa-sessions article').count(), 1);
console.log('Plan review, shared pricing, invitations, role changes, audit, settings and security passed.');
for (const role of ['ADMIN', 'EDITOR', 'VIEWER']) {
  await go(''); await page.getByLabel('Preview role').selectOption(role); await settle();
  assert.equal(await page.locator('.pa-sidebar a[href="/admin/settings"]').count(), 0);
  assert.equal(await page.locator('.pa-sidebar a[href="/admin/admin-team"]').count(), role === 'ADMIN' ? 1 : 0);
  await go('/plans/pro/edit'); await page.getByRole('heading', { name: 'Access restricted' }).waitFor();
  await go('/settings'); await page.getByRole('heading', { name: 'Access restricted' }).waitFor();
  await go('/companies/company-2'); assert.equal(await page.getByRole('button', { name: 'Suspend access', exact: true }).count(), role === 'ADMIN' ? 1 : 0); assert.equal(await page.getByRole('button', { name: 'Edit administrative notes' }).count(), role === 'VIEWER' ? 0 : 1);
  await go('/plans'); assert.equal(await page.getByRole('link', { name: 'Edit', exact: true }).count(), 0);
}
await page.getByLabel('Preview role').selectOption('SUPER_ADMIN'); await settle();
await go('/companies/missing-id'); await page.getByRole('heading', { name: 'This record could not be found.' }).waitFor();
await go('/unknown-route'); await page.getByRole('heading', { name: 'Page not found' }).waitFor();
await go(''); await page.getByRole('button', { name: 'Language', exact: true }).click(); await page.waitForFunction(() => document.documentElement.dir === 'rtl');
await page.screenshot({ path: 'tmp/admin-screens/overview-ar.png', fullPage: true });
for (const width of [1024, 768, 390]) {
  await page.setViewportSize({ width, height: 900 });
  for (const path of ['', '/companies', '/companies/company-2', '/users', '/subscriptions', '/plans', '/plans/pro/edit', '/features', '/admin-team', '/audit-logs', '/settings', '/profile', '/security']) { await go(path); await overflow(`${width} AR ${path}`); assert.equal((await page.locator('.pa-main').innerText()).includes('platformAdmin.'), false, `Untranslated ${path}`); }
}
await go('/companies'); await page.screenshot({ path: 'tmp/admin-screens/companies-ar-mobile.png', fullPage: true });
await page.getByRole('button', { name: 'فتح القائمة' }).click(); await page.getByRole('dialog').waitFor(); await page.keyboard.press('Escape'); assert.equal(await page.getByRole('dialog').count(), 0);
await page.getByRole('button', { name: 'اللغة', exact: true }).click(); await go('/plans/pro/edit'); await page.getByRole('tab', { name: 'Pricing & billing' }).click(); await page.getByRole('spinbutton', { name: 'Monthly price', exact: true }).fill('119'); await page.getByRole('button', { name: 'Review changes' }).click(); await overflow('mobile review dialog'); await page.screenshot({ path: 'tmp/admin-screens/review-en-mobile.png', fullPage: true });
await page.getByRole('button', { name: 'Cancel', exact: true }).click(); await page.getByRole('button', { name: 'Cancel', exact: true }).click();
await go('/companies'); await overflow('mobile English');
assert.deepEqual(errors, []);
await browser.close();
console.log('PASS: all routes and workflows, 4 roles, 403/404, loading/empty/error, keyboard modal, audit diffs, EN/AR + RTL, desktop/tablet/mobile overflow, no runtime errors.');


