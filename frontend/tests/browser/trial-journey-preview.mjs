// Offline browser acceptance: route every request; no listening API or providers.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright-core';

const operation = '11111111-1111-4111-8111-111111111111';
const other = '22222222-2222-4222-8222-222222222222';
const origin = 'http://127.0.0.1:19473';
const chrome = process.env.CHROMIUM_PATH || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
].find(existsSync);
assert.ok(chrome, 'Installed Chromium required');
const fixture = `
    import React, { useState } from 'react';
    import { createRoot } from 'react-dom/client';
    import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
    import { I18nProvider } from './src/app/providers/I18nProvider.jsx';
    import { loadLocale } from './src/shared/lib/i18n.js';
    import { useAuthStore } from './src/features/auth/store/authStore.js';
    import httpClient, { configureHttpClientAuth } from './src/shared/lib/httpClient.js';
    import { TrialJourneyPreview } from './src/features/billing/components/TrialJourneyPreview.jsx';
    httpClient.defaults.baseURL = location.origin;
    configureHttpClientAuth({ getAccessToken: () => 'synthetic-offline-token' });
    useAuthStore.setState({ tenantId: 'tenant-original', user: { id: 'actor-original' } });
    const client = new QueryClient();
    window.refreshPreview = () => client.invalidateQueries({ queryKey: ['trialJourneyPreview'] });
    window.switchIdentity = () => useAuthStore.setState({ tenantId: 'tenant-other', user: { id: 'actor-other' } });
    function Fixture() {
      const [props, setProps] = useState({ operationId: '${operation}' });
      window.showPreview = value => setProps(value);
      return <TrialJourneyPreview {...props} />;
    }
    loadLocale(localStorage.getItem('ceopro_locale') || 'en').then(() => {
      createRoot(document.getElementById('root')).render(
        <QueryClientProvider client={client}><I18nProvider><Fixture /></I18nProvider></QueryClientProvider>
      );
      window.fixtureReady = true;
    });`;
const input = resolve('.trial-preview-offline.jsx');
const bundled = await build({
  configFile: false, envDir: false, logLevel: 'silent',
  define: { 'import.meta.env.VITE_RECURRING_JOURNEY_PREVIEW_ENABLED': JSON.stringify('false'),
    'process.env.NODE_ENV': JSON.stringify('production') },
  plugins: [react(), { name: 'offline-fixture',
    resolveId(id) { if (id === input) return input; },
    load(id) { if (id === input) return fixture; },
  }],
  build: { write: false, minify: false, lib: { entry: input, formats: ['es'] },
    rollupOptions: { output: { codeSplitting: false } } },
});
const outputs = Array.isArray(bundled) ? bundled : [bundled];
const script = outputs.flatMap(result => result.output).find(item => item.type === 'chunk').code;
const browser = await chromium.launch({ executablePath: chrome, headless: true });
const checks = [];
try {
  for (const locale of ['en', 'ar']) {
    const messages = JSON.parse(readFileSync(`src/assets/locales/${locale}.json`, 'utf8')).billing.trialJourney;
    const context = await browser.newContext();
    const page = await context.newPage();
    const calls = [], errors = [], unexpected = [];
    let state = 'eligible', status = 200;
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(value => localStorage.setItem('ceopro_locale', value), locale);
    await page.route('**/*', async route => {
      const request = route.request(); const url = request.url();
      if (url === origin+'/') return route.fulfill({ contentType: 'text/html', body: '<html><body><div id="root"></div><script type="module" src="/fixture.js"></script></body></html>' });
      if (url === origin+'/fixture.js') return route.fulfill({ contentType: 'text/javascript', body: script });
      if (url.startsWith(origin+'/billing/trial-journeys/')) {
        calls.push({ url, method: request.method(), auth: request.headers().authorization });
        return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(status === 200 ? {
          operation_id: url.split('/').at(-1), state, reason: 'synthetic-read-checkpoint',
          commercial_terms: state === 'conflict' ? null : { plan_key: 'frozen-original-plan', renewal_amount: '12345678901234.123456789', currency: 'USD', interval_months: 3, trial_duration_days: 14 },
        } : { detail: 'revoked' }) });
      }
      unexpected.push(url); return route.abort();
    });
    await page.goto(origin);
    await page.waitForFunction(() => window.fixtureReady).catch(error => {
      throw new Error(JSON.stringify({ errors, unexpected, cause: error.message }));
    });
    assert.equal(await page.locator('section').count(), 0);
    assert.equal(calls.length, 0); checks.push(locale+': default disabled makes no request');
    await page.evaluate(op => window.showPreview({ operationId: op, enabled: true }), operation);
    await page.getByText('12345678901234.123456789 USD', { exact: true }).waitFor();
    assert.equal(await page.getByRole('status').textContent(), messages.eligible);
    assert.equal(await page.locator('section').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');
    assert.equal(await page.locator('section button, section a, section input').count(), 0);
    checks.push(locale+': frozen exact terms, direction and no action controls');
    for (const next of ['pending_verification', 'conflict', 'expired', 'blocked']) {
      state = next;
      await page.evaluate(() => window.refreshPreview());
      await page.getByRole('status').filter({ hasText: messages[next] }).waitFor();
      if (next === 'conflict') assert.equal(await page.locator('dl').count(), 0);
    }
    checks.push(locale+': pending/conflict/expired/blocked display');
    status = 403;
    await page.evaluate(() => window.refreshPreview());
    await page.getByRole('status').filter({ hasText: messages.blocked }).waitFor();
    assert.equal(await page.locator('dl').count(), 0);
    checks.push(locale+': authorization denial removes previous commercial data');
    await page.evaluate(() => window.switchIdentity());
    await page.waitForFunction(() => document.querySelector('[role="status"]')?.textContent !== 'Loading...');
    assert.equal(await page.locator('dl').count(), 0);
    await Promise.all([page.waitForResponse(response => response.url().endsWith(other)),
      page.evaluate(op => window.showPreview({ operationId: op, enabled: true }), other)]);
    assert.equal(await page.locator('dl').count(), 0);
    assert.ok(calls.every(call => call.method === 'GET' && call.auth === 'Bearer synthetic-offline-token'));
    assert.equal(unexpected.length, 0, JSON.stringify(unexpected));
    assert.deepEqual(errors, []);
    checks.push(locale+': identity/operation switch, only authenticated exact GETs, no external traffic');
    await context.close();
  }
  console.log(JSON.stringify({ status: 'PASS', checks }, null, 2));
} finally { await browser.close(); }
