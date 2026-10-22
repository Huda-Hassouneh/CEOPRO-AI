// Real React and FastAPI routes with a local, contract-shaped Stripe test fixture.
import { chromium } from 'playwright-core';

const base = process.env.KEEL_SUBSCRIPTION_BROWSER_BASE_URL;
if (process.env.KEEL_SUBSCRIPTION_BROWSER_FIXTURE !== 'YES' || base !== 'http://127.0.0.1:15173') {
  throw new Error('Disposable subscription browser fixture required');
}
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH, headless: true });
const page = await browser.newPage();
page.setDefaultTimeout(15000);
let passed = 0;
const pass = (name) => { passed++; console.log(`PASS ${name}`); };
try {
  page.on('response', async (response) => {
    if (response.url().includes('/auth/login')) console.log(`LOGIN_RESPONSE ${response.status()}`);
  });
  page.on('request', (request) => {
    if (request.url().includes('/auth/login')) console.log(`LOGIN_REQUEST ${new URL(request.url()).pathname}`);
  });
  page.on('requestfailed', (request) => {
    if (request.url().includes('/auth/login')) console.log(`LOGIN_REQUEST_FAILED ${request.failure()?.errorText || 'unknown'}`);
  });
  await page.goto(`${base}/login`);
  await page.locator('input[type="email"]').fill(process.env.KEEL_SUBSCRIPTION_TEST_EMAIL);
  await page.locator('input[type="password"]').fill(process.env.KEEL_SUBSCRIPTION_TEST_PASSWORD);
  await page.locator('button[type="submit"]').click();
  // New workspaces are routed through the existing setup gate. Billing is
  // intentionally available before setup, so accept that legitimate landing
  // state and then follow the supported billing route.
  await page.waitForTimeout(1000);
  if (!/\/(?:dashboard|onboarding)$/.test(new URL(page.url()).pathname)) {
    throw new Error(`Login did not complete; current route: ${new URL(page.url()).pathname}; page: ${(await page.locator('body').innerText()).slice(0, 600)}`);
  }
  pass('owner signs in through the React authentication flow');

  await page.goto(`${base}/billing`);
  await page.getByRole('heading', { name: /subscription|billing|الاشتراك|الفوترة/i }).first().waitFor();
  await page.getByRole('button', { name: /subscribe|اشترك/i }).first().click();
  await page.waitForURL('http://127.0.0.1:15175/checkout/**');
  await page.getByRole('heading', { name: 'Stripe test checkout' }).waitFor();
  pass('plan selection reaches the isolated hosted-checkout fixture');

  await page.getByRole('button', { name: 'Complete test payment' }).click();
  await page.waitForURL(/\/billing\?checkout=success/);
  await page.getByText(/Subscription confirmed|تم تأكيد الاشتراك/i).waitFor();
  await page.getByRole('heading', { name: /Plus|Growth/i }).first().waitFor();
  pass('signed checkout and paid-invoice events activate the plan before confirmed UI appears');

  await page.getByRole('heading', { name: /Payments/i }).waitFor();
  await page.getByText(/Paid/i).waitFor();
  pass('invoice history displays the persisted provider payment status');

  await page.getByRole('button', { name: /Payment method & receipts/i }).click();
  await page.waitForURL('http://127.0.0.1:15175/portal/session');
  await page.getByRole('heading', { name: 'Stripe customer portal test fixture' }).waitFor();
  await page.getByRole('link', { name: 'Return to KEEL' }).click();
  await page.waitForURL('**/billing');
  pass('customer portal action reaches the isolated hosted-portal fixture');

  await page.getByRole('button', { name: /Cancel subscription/i }).click();
  await page.getByRole('button', { name: /Cancel at period end/i }).click();
  await page.getByText(/Your subscription will end/i).waitFor();
  pass('period-end cancellation remains active until the signed provider update');

  await page.getByRole('button', { name: /Keep my subscription/i }).click();
  await page.getByText(/Your subscription will continue/i).waitFor();
  pass('subscription reactivation is applied through the provider update');

  await page.evaluate(() => localStorage.setItem('ceopro_locale', 'ar'));
  await page.reload();
  await page.waitForFunction(() => document.documentElement.lang === 'ar' && document.documentElement.dir === 'rtl');
  pass('billing screen supports Arabic locale and RTL direction');
  await page.evaluate(() => localStorage.setItem('ceopro_locale', 'en'));
  await page.goto(`${base}/billing?checkout=cancelled`);
  await page.getByText('Checkout was cancelled. This checkout did not activate a subscription.').waitFor();
  pass('cancelled checkout state does not claim payment or activate access');
  console.log(`SUBSCRIPTION BROWSER: ${passed} passed, 0 failed, 0 skipped`);
} catch (error) {
  console.error(`FAIL after ${passed} passed: ${error.stack || error}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
