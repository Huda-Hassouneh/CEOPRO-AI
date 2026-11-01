// No provider request or payment. Real disposable API and restricted DB roles.
import { chromium } from 'playwright-core';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const locale = process.env.E2E_LOCALE || 'en';
const t = JSON.parse(readFileSync(`src/assets/locales/${locale}.json`, 'utf8')).billing.customPlan;
const { APP_URL, API_URL, CHROMIUM_PATH, SCENARIO } = process.env;
if (!APP_URL?.startsWith('http://127.0.0.1:') || !API_URL?.startsWith('http://127.0.0.1:')) throw new Error('Loopback test runtime required');
const browser = await chromium.launch({ executablePath: CHROMIUM_PATH, headless: true });
try {
  const page = await browser.newPage();
  await page.addInitScript(value => localStorage.setItem('ceopro_locale', value), locale);
  const errors = [];
  const failures = [];
  const requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('requestfailed', request => failures.push({ url: request.url(), failure: request.failure() }));
  page.on('request', request => { if (request.url().includes('/billing/')) requests.push(request.url()); });
  await page.goto(APP_URL + '/tests/browser/custom-self-service.html');
  await page.locator('.ceopro-custom-feature-card').first().waitFor();
  const card = page.locator('.ceopro-custom-feature-card').filter({ hasText: t.featureNames.connected_data_sources });
  await card.getByRole('checkbox').check();
  const response = page.waitForResponse(r => r.url() === API_URL + '/billing/custom-offers/pricing-preview' && r.request().method() === 'POST');
  await card.getByRole('textbox').fill(SCENARIO === 'quota' ? '500001' : SCENARIO === 'price' ? '3000' : '10');
  let actual = await (await response).json();
  // Ignore an earlier zero-quantity debounce response if it was already in flight.
  if (!actual.pricingAvailable) actual = await (await page.waitForResponse(r => r.url() === API_URL + '/billing/custom-offers/pricing-preview')).json();
  await page.locator('.custom-plan-price strong').waitFor();
  assert.equal(actual.currency, 'JOD');
  assert.equal(actual.paymentCurrency, 'USD');
  if (SCENARIO === 'automatic') {
    assert.equal(actual.reviewRequired, false);
    assert.equal(actual.price, '36.00');
    await page.getByRole('button', { name: t.continueCheckout, exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: t.continueCheckout, exact: true }).isEnabled(), true);
    // Transport refusal only: no Stripe call. Retry must retain the frozen
    // preview and request identity, and the customer must see the blocker.
    const checkoutRequests = [];
    await page.route(API_URL + '/billing/custom-offers/checkout', async route => {
      if (route.request().method() !== 'POST') return route.continue();
      checkoutRequests.push(route.request().postDataJSON());
      await route.fulfill({ status: 409, contentType: 'application/json',
        headers: { 'access-control-allow-origin': APP_URL },
        body: JSON.stringify({ detail: { reason: 'checkout_pending', message: 'Synthetic checkout blocker' } }) });
    });
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        await Promise.all([
          page.waitForResponse(r => r.url() === API_URL + '/billing/custom-offers/checkout' && r.request().method() === 'POST', { timeout: 8000 }),
          page.getByRole('button', { name: t.continueCheckout, exact: true }).click({ timeout: 8000 }),
        ]);
      } catch (error) {
        throw new Error(JSON.stringify({ attempt, checkoutRequests, requests, failures, errors, alerts: await page.getByRole('alert').allTextContents(), buttons: await page.getByRole('button').evaluateAll(nodes => nodes.map(node => ({ text: node.textContent, disabled: node.disabled, busy: node.getAttribute('aria-busy') }))), cause: error.message }));
      }
      await page.getByRole('alert').filter({ hasText: 'Synthetic checkout blocker' }).waitFor();
    }
    assert.equal(checkoutRequests.length, 2);
    assert.deepEqual(checkoutRequests[0], checkoutRequests[1]);
    assert.deepEqual(Object.keys(checkoutRequests[0]).sort(), ['idempotency_key', 'preview_id']);
    const repriced = page.waitForResponse(r => r.url() === API_URL + '/billing/custom-offers/pricing-preview' && r.request().method() === 'POST');
    await page.getByLabel(t.periodLabel).selectOption('three-months');
    const term = await (await repriced).json();
    assert.equal(term.price, '97.20');
    assert.equal(term.paymentAmount, '137.09');
    await page.getByRole('button', { name: t.continueCheckout, exact: true }).waitFor();
  } else if (SCENARIO === 'existing') {
    assert.equal(actual.checkoutAllowed, false);
    assert.equal(await page.getByRole('button', { name: t.continueCheckout, exact: true }).isDisabled(), true);
    await page.getByText(t.existingSubscription).waitFor();
  } else {
    const reason = { quota: 'QUOTA_ABOVE_AUTOMATIC_LIMIT:connected_data_sources', price: 'PRICE_ABOVE_AUTOMATIC_LIMIT', unverified: 'UNVERIFIED_VENDOR_RATE' }[SCENARIO];
    assert.ok(actual.reasons.includes(reason), JSON.stringify(actual));
    assert.equal(actual.reviewRequired, true);
    assert.equal(await page.getByRole('button', { name: t.continueCheckout, exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: t.requestQuote, exact: true }).isEnabled(), true);
  }
  assert.deepEqual(errors, []);
  assert.equal(await page.locator('.custom-plan-page').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');
  console.log('PASS custom builder: ' + SCENARIO);
} finally { await browser.close(); }
