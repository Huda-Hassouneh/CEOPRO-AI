// Run from frontend: node tests/browser/custom-quote.mjs
// Real Chrome, production React page/SetupGate, synthetic HTTP responses.
// No backend, database, provider credentials or payment requests are needed.
import assert from 'node:assert/strict';
import { existsSync, readFileSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { createServer } from 'vite';
import { chromium } from 'playwright-core';

process.env.KEEL_DEV_ISOLATED = '1';
process.env.VITE_API_BASE_URL = '/api';
const executablePath = process.env.CHROMIUM_PATH || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
].find(existsSync);
if (!executablePath) throw new Error('Set CHROMIUM_PATH to the installed Chrome executable');
const server = await createServer({ server: { host: '127.0.0.1', port: 0, open: false } });
let browser;
let passed = 0;
try {
  await server.listen();
  const base = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ executablePath, headless: true });
  const run = async (locale, customer, edge = '') => {
    const messages = JSON.parse(readFileSync(`src/assets/locales/${locale}.json`, 'utf8')).billing.customPlan;
    const existing = customer !== 'none';
    let subscription = { available: true, assigned: existing, hasAccess: existing, hasSubscription: ['standard', 'custom'].includes(customer), status: customer === 'trial' ? 'trialing' : 'active', planId: customer === 'custom' ? 'custom' : 'starter', limits: { products: existing ? 3 : 0 }, entitlements: [] };
    let quote = { quote_id: 'synthetic-quote', state: 'submitted', revision_state: 'submitted', revision_number: 1, valid_until: new Date(Date.now() + 3600000).toISOString(), feature_quantities: { ai_credits: 1000 }, configuration: { enabled_features: ['market_intelligence'] }, commercial_terms: { currency: 'JOD', amount: '63.81', billingPeriodMonths: 1, periodCode: 'monthly', paymentCurrency: 'USD', paymentAmountUsd: '90.00' }, events: [] };
    let posts = 0;
    let rejectCheckout = false;
    let subscriptionFailure = false;
    const context = await browser.newContext({ viewport: { width: locale === 'ar' ? 390 : 1280, height: 900 } });
    try {
      await context.addInitScript(value => localStorage.setItem('ceopro_locale', value), locale);
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await context.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (url.origin !== base) return route.abort();
        if (!url.pathname.startsWith('/api/')) return route.continue();
        const path = url.pathname.slice(4);
        let body;
        let status = 200;
        if (path === '/billing/subscription') {
          body = subscription;
          if (subscriptionFailure) { status = 503; body = {}; }
        } else if (path === '/billing/plans') body = { plans: [], payments_enabled: true };
        else if (path === '/settings/company') body = { onboarding_completed_at: '2026-11-01T00:00:00Z' };
        else if (path.endsWith('/accept')) {
          posts += 1;
          const state = edge === 'server-expiry' ? 'expired' : 'accepted';
          quote = { ...quote, state, revision_state: state };
          body = { state, access_activated: false };
        } else if (path.endsWith('/checkout-attempts')) {
          posts += 1;
          if (edge === 'busy') await new Promise(resolve => setTimeout(resolve, 750));
          status = 409;
          body = { detail: { reason: rejectCheckout ? 'subscription_exists' : 'synthetic_no_payment', message: 'Fixture: no provider call' } };
        } else if (path === '/billing/custom-offers/quotes/synthetic-quote') body = quote;
        else throw new Error(`Unexpected fixture API: ${path}`);
        await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
      });
      const open = async () => {
        await page.goto(base + '/tests/browser/custom-quote.html');
        await page.locator('.custom-plan-offer-status').waitFor();
      };
      const refresh = async () => {
        const response = page.waitForResponse(r => r.url().endsWith('/quotes/synthetic-quote'));
        await page.getByRole('button', { name: messages.refreshStatus, exact: true }).click();
        await response;
      };
      await open();
      if (!edge) {
        assert.equal(await page.locator('.custom-plan-page').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');
        assert.equal(await page.locator('.custom-plan-offer-status').getAttribute('role'), 'status');
        assert.equal(await page.locator('.custom-plan-offer-status').getAttribute('aria-live'), 'polite');
        await page.getByRole('heading', { name: messages.pendingTitle, exact: true }).waitFor();
        if (process.env.E2E_OUTPUT_DIR) {
          mkdirSync(process.env.E2E_OUTPUT_DIR, { recursive: true });
          await page.screenshot({ path: join(process.env.E2E_OUTPUT_DIR, `pending-${locale}-${customer}.png`), fullPage: true });
        }
        await page.getByText(messages.featureNames.ai_credits + ':', { exact: false }).waitFor();
        assert.equal(await page.getByRole('button', { name: messages.continueCheckout, exact: true }).count(), 0);
        assert.notEqual(await page.locator('.custom-plan-waiting').evaluate(el => getComputedStyle(el).animationName), 'none');
        await page.emulateMedia({ reducedMotion: 'reduce' });
        assert.equal(await page.locator('.custom-plan-waiting').evaluate(el => getComputedStyle(el).animationName), 'none');
        if (existing) {
          await page.getByText(messages.currentAccessPreserved, { exact: false }).waitFor();
          await page.getByRole('link', { name: messages.returnDashboard, exact: true }).click();
          await page.getByTestId('dashboard').waitFor();
          assert.match(await page.getByTestId('dashboard').innerText(), /:3/);
          await page.getByRole('link', { name: 'Quote', exact: true }).click();
        }
        quote = { ...quote, state: 'approved', revision_state: 'approved' };
        await refresh();
        await page.getByRole('button', { name: messages.acceptOffer, exact: true }).click();
        if (['standard', 'custom'].includes(customer)) {
          await page.getByText(messages.replacementUnavailable, { exact: true }).waitFor();
          assert.equal(posts, 1); // Acceptance only, never duplicate Checkout.
          assert.equal(subscription.limits.products, 3);
          assert.deepEqual(subscription.entitlements, []); // Requested module not granted.
        } else await page.getByRole('button', { name: messages.continueCheckout, exact: true }).waitFor();
        quote = { ...quote, state: 'rejected', revision_state: 'rejected' };
        await refresh();
        await page.getByText(messages.offerRejected, { exact: true }).waitFor();
        assert.equal(await page.getByRole('button', { name: messages.acceptOffer, exact: true }).count(), 0);
        quote = { ...quote, state: 'approved', revision_state: 'approved', valid_until: new Date(Date.now() - 1000).toISOString() };
        await page.reload();
        await page.getByText(messages.offerExpired, { exact: true }).waitFor();
        assert.equal(await page.getByRole('button', { name: messages.acceptOffer, exact: true }).count(), 0);
      } else {
        const approved = ['live-expiry', 'server-expiry'].includes(edge);
        quote = { ...quote, state: approved ? 'approved' : 'accepted', revision_state: approved ? 'approved' : 'accepted' };
        if (edge === 'live-expiry') quote.valid_until = new Date(Date.now() + 2000).toISOString();
        if (edge === 'paid-history') {
          quote.valid_until = new Date(Date.now() - 1000).toISOString();
          quote.events = [{ action: 'contract_activated' }];
        }
        await refresh();
        if (edge === 'live-expiry') {
          await page.getByRole('button', { name: messages.acceptOffer, exact: true }).waitFor();
          await page.getByText(messages.offerExpired, { exact: true }).waitFor();
          assert.equal(await page.getByRole('button', { name: messages.acceptOffer, exact: true }).count(), 0);
        } else if (edge === 'server-expiry') {
          await page.getByRole('button', { name: messages.acceptOffer, exact: true }).click();
          await page.getByRole('heading', { name: messages.status.expired, exact: true }).waitFor();
          assert.equal(await page.getByText(messages.acceptedNotActivated, { exact: true }).count(), 0);
          assert.equal(posts, 1);
        } else if (edge === 'paid-history') {
          await page.getByRole('link', { name: messages.manageSubscription, exact: true }).waitFor();
          await page.getByRole('heading', { name: messages.status.accepted, exact: true }).waitFor();
        } else {
          const checkout = page.getByRole('button', { name: messages.continueCheckout, exact: true });
          await checkout.waitFor();
          if (edge === 'stale-client') subscription = { ...subscription, hasSubscription: true, assigned: true, hasAccess: true };
          if (edge === 'server-race') rejectCheckout = true;
          if (edge === 'read-failure') subscriptionFailure = true;
          await checkout.click();
          if (edge === 'busy') {
            const busy = page.locator('button[aria-busy="true"]');
            await busy.waitFor();
            assert.equal(await busy.isDisabled(), true);
            await busy.evaluate(button => button.click()); // Disabled native button cannot submit again.
          }
          await page.getByRole('alert').waitFor();
          assert.equal(posts, ['server-race', 'busy'].includes(edge) ? 1 : 0);
          if (!['read-failure', 'busy'].includes(edge)) await page.getByRole('alert').filter({ hasText: messages.replacementUnavailable }).waitFor();
          if (edge !== 'busy') assert.equal(await checkout.count(), 0);
        }
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      assert.equal(await page.getByText(/billing\.customPlan\./).count(), 0);
      if (!existing && !edge) {
        await page.goto(base + '/tests/browser/custom-quote.html?route=dashboard');
        await page.getByTestId('safe-navigation').waitFor();
        assert.equal(await page.getByTestId('dashboard').count(), 0);
      }
      assert.deepEqual(errors, []);
      if (process.env.E2E_OUTPUT_DIR) {
        mkdirSync(process.env.E2E_OUTPUT_DIR, { recursive: true });
        await page.screenshot({ path: join(process.env.E2E_OUTPUT_DIR, `quote-${locale}-${customer}-${edge || 'lifecycle'}.png`), fullPage: true });
      }
      passed += 1;
      console.log(`PASS ${locale} ${customer} ${edge || 'pending/approval/rejection/expiry/access'}`);
    } finally { await context.close(); }
  };
  for (const locale of ['en', 'ar']) {
    for (const customer of ['none', 'standard', 'custom', 'trial']) await run(locale, customer);
    for (const edge of ['live-expiry', 'server-expiry', 'stale-client', 'server-race', 'read-failure', 'paid-history', 'busy']) await run(locale, 'none', edge);
  }
  console.log(`PASS ${passed} Chrome quote scenarios (offline HTTP fixtures)`);
} finally {
  await browser?.close();
  await server.close();
}
