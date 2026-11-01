// UI acceptance only. Backend authority is tested separately on disposable PostgreSQL.
import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { createRequire } from 'node:module';
import { createServer } from 'vite';
import { chromium } from 'playwright-core';

const out = resolve(process.env.E2E_OUTPUT || '../.dev/evidence/standard-plan-creation-review');
mkdirSync(out, { recursive: true });
const results = [], consoleIssues = [], pageErrors = [], unexpected = [];
const axe = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8');
const server = await createServer({ cacheDir: join(out, 'vite-cache'), server: { host: '127.0.0.1', port: 0 } });
let browser;
const numeric = ['ai_credits', 'data_credits', 'document_storage_mb'];
const metadata = [
  ['ai_credits', 'AI Credits', 'أرصدة الذكاء الاصطناعي', 'credits'],
  ['data_credits', 'Data Credits', 'أرصدة البيانات', 'credits'],
  ['document_storage_mb', 'Document storage', 'تخزين المستندات', 'MB'],
  ['market_intelligence', 'Market Intelligence', 'معلومات السوق', ''],
].map(([feature_code, display_name, display_name_ar, unit]) => ({ feature_code, display_name, display_name_ar, unit }));
try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
  for (const locale of ['en', 'ar']) for (const width of (process.env.E2E_WIDTH ? [Number(process.env.E2E_WIDTH)] : [1440, 1280, 1024, 768, 430, 390])) {
    const messages = JSON.parse(readFileSync(`src/assets/locales/${locale}.json`, 'utf8'));
    const t = key => key.split('.').reduce((value, part) => value?.[part], messages);
    const context = await browser.newContext({ viewport: { width, height: 1000 } });
    await context.addInitScript(value => localStorage.setItem('ceopro_locale', value), locale);
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const writes = [];
    const seeded = { plan_key: 'starter', display_name: 'Standard', display_name_ar: 'ستاندرد',
      monthly_price: '55.00', currency: 'USD', trial_days: 14, tier_level: 1, self_serve: true, is_active: true,
      configuration_status: 'READY', feature_limits: [], entitlements: [],
      prices: [{ period_code: 'monthly', interval_months: 1, amount: '55.00', stripe_price_id: 'price_synthetic' }] };
    const plans = [structuredClone(seeded)];
    let rejectTerms = false;
    page.on('pageerror', error => pageErrors.push({ locale, width, message: error.message }));
    page.on('console', message => {
      // Chromium logs the intentionally exercised conflict/validation responses as network errors.
      if (['error', 'warning'].includes(message.type()) && !/^Failed to load resource: the server responded with a status of (409|422)\b/.test(message.text())) {
        consoleIssues.push({ locale, width, message: message.text() });
      }
    });
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (['fonts.googleapis.com', 'fonts.gstatic.com'].includes(url.hostname)) return route.continue();
      if (url.pathname === '/favicon.ico') return route.fulfill({ status: 204 });
      if (!/^\/(api\/)?(platform|billing)\//.test(url.pathname)) {
        if (url.origin !== origin) { unexpected.push(request.url()); return route.abort(); }
        return route.continue();
      }
      const path = url.pathname.replace(/^\/api/, ''), method = request.method();
      const headers = { 'access-control-allow-origin': origin, 'access-control-allow-credentials': 'true',
        'access-control-allow-methods': 'GET,POST,PATCH,OPTIONS', 'access-control-allow-headers': 'authorization,content-type' };
      const reply = (body, status = 200) => route.fulfill({ status, headers, contentType: 'application/json', body: JSON.stringify(body) });
      if (method === 'OPTIONS') return reply({});
      if (method !== 'GET') writes.push({ path, method, body: request.postDataJSON() });
      if (path === '/platform/billing/standard-plans') return reply({ plans });
      if (path === '/platform/billing/plan-templates') return reply(JSON.parse(readFileSync(resolve('../backend/config/billing/standard_plan_catalog.json'), 'utf8')));
      if (path === '/platform/billing/feature-catalog') return reply({ features: metadata });
      if (path === '/billing/custom-offers/configurator') return reply({
        features: metadata.filter(f => numeric.includes(f.feature_code)).map(f => ({ featureCode: f.feature_code, unit: f.unit, aggregationType: 'sum', resetCycle: 'billing_period' })),
        modules: [{ featureCode: 'market_intelligence' }],
      });
      if (path === '/platform/billing/promotions') return reply({ items: [] });
      if (path === '/platform/billing/pricing-studio') return reply({ provider_readiness: { providers: [] }, selected_policy: null });
      if (path === '/platform/billing/plans' && method === 'POST') {
        const body = request.postDataJSON();
        if (plans.some(p => p.plan_key === body.plan_key)) return reply({ detail: 'Historical plan key already exists.' }, 409);
        if (rejectTerms) return reply({ detail: [{ loc: ['body', 'monthly_price'], msg: 'Invalid terms' }] }, 422);
        const created = { ...body, self_serve: true, is_active: false, stripe_setup_required: true,
          configuration_status: 'MISSING_FEATURES', feature_limits: [], entitlements: [],
          prices: [{ period_code: 'monthly', interval_months: 1, amount: body.monthly_price }] };
        plans.push(created);
        return reply({ plan: created, is_active: false, stripe_setup_required: true }, 201);
      }
      const mutation = path.match(/^\/platform\/billing\/plans\/([^/]+)\/(features|status)$/);
      if (mutation && method === 'PATCH') {
        const plan = plans.find(p => p.plan_key === mutation[1]), body = request.postDataJSON();
        if (mutation[2] === 'features') {
          if (numeric.includes(body.feature_code)) plan.feature_limits.push({ feature_code: body.feature_code, limit_value: body.limit_value, unit: metadata.find(f => f.feature_code === body.feature_code).unit });
          else plan.entitlements.push(body.feature_code);
          plan.configuration_status = 'READY_TO_ACTIVATE';
        } else {
          if (!plan.feature_limits.length && !plan.entitlements.length) return reply({ detail: 'Incomplete plan' }, 422);
          plan.is_active = body.active;
          plan.configuration_status = 'STRIPE_SETUP_REQUIRED';
        }
        return reply({ plan_key: plan.plan_key, existing_assignments_preserved: true });
      }
      unexpected.push(`${method} ${path}`);
      return reply({ detail: 'Unexpected fixture request' }, 500);
    });
    await page.goto(origin + '/tests/browser/standard-plan-creation.html');
    const create = page.getByRole('button', { name: t('billing.catalog.plans.create'), exact: true });
    await create.waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.getByText(t('billing.catalog.plans.configurationStates.READY'), { exact: true }).waitFor();
    assert.deepEqual(writes, [], 'Navigation must not mutate configuration');
    await create.click();
    const dialog = page.getByRole('dialog');
    await dialog.waitFor();
    await page.addScriptTag({ content: axe });
    const auditDialog = async () => {
      const audit = await page.evaluate(() => window.axe.run(document.querySelector('[role="dialog"]'), { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] } }));
      assert.deepEqual(audit.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.target) })), []);
    };
    const close = dialog.getByRole('button', { name: t('common.close'), exact: true });
    assert.equal(await close.evaluate(e => e === document.activeElement), true);
    await page.keyboard.press('Shift+Tab');
    assert.equal(await dialog.getByRole('button', { name: t('billing.catalog.plans.saveDraft'), exact: true }).evaluate(e => e === document.activeElement), true);
    await page.keyboard.press('Tab');
    assert.equal(await close.evaluate(e => e === document.activeElement), true);
    await page.keyboard.press('Escape'); await dialog.waitFor({ state: 'hidden' });
    assert.equal(await create.evaluate(e => e === document.activeElement), true);
    await create.click(); await dialog.waitFor();
    assert.equal(await dialog.evaluate(e => getComputedStyle(e).direction), locale === 'ar' ? 'rtl' : 'ltr');
    const key = dialog.getByLabel(t('billing.catalog.plans.planKey'), { exact: true });
    const save = dialog.getByRole('button', { name: t('billing.catalog.plans.saveDraft'), exact: true });
    const fill = async (field, value) => dialog.getByLabel(t(field), { exact: true }).fill(value);
    await fill('billing.catalog.fields.name', 'New Regional Plan');
    await fill('billing.catalog.fields.nameAr', 'خطة إقليمية جديدة');
    await fill('billing.catalog.fields.tier', '4');
    await fill('billing.catalog.fields.trialDays', '7');
    await fill('billing.catalog.plans.monthlyPriceUsd', '82.50');
    await fill('billing.catalog.fields.description', 'LongDescription'.repeat(60));
    await fill('billing.catalog.fields.descriptionAr', 'وصف طويل للخطة الجديدة '.repeat(40));
    await fill('billing.catalog.plans.auditReason', 'Synthetic UI audit');
    await key.fill('valid_key');
    await fill('billing.catalog.fields.trialDays', '366'); await save.click();
    assert.equal(await dialog.getByLabel(t('billing.catalog.fields.trialDays'), { exact: true }).evaluate(e => e.validity.rangeOverflow), true);
    assert.equal(writes.length, 0);
    await fill('billing.catalog.fields.trialDays', '7');
    await key.fill('Invalid Key'); await save.click();
    assert.equal(await key.evaluate(e => e.validity.patternMismatch), true);
    assert.equal(writes.length, 0);
    await key.fill('custom'); await save.click();
    await dialog.getByRole('alert').waitFor();
    assert.equal(writes.length, 0);
    await key.fill('starter'); await save.click();
    await dialog.getByRole('alert').filter({ hasText: t('billing.catalog.plans.identityConflict') }).waitFor();
    assert.equal(await dialog.getByRole('alert').evaluate(e => document.activeElement === e), true);
    const newKey = 'regional_' + 'a'.repeat(41);
    await key.fill(newKey);
    rejectTerms = true; await save.click();
    await dialog.getByRole('alert').filter({ hasText: t('billing.catalog.plans.invalidTerms') }).waitFor();
    rejectTerms = false;
    for (const [code, label] of [['three-months', 'threeMonths'], ['six-months', 'sixMonths'], ['yearly', 'yearly']]) {
      const name = t(`billing.catalog.plans.periods.${label}`);
      await dialog.getByRole('checkbox', { name, exact: true }).check();
      await dialog.getByLabel(`${name} — ${t('billing.catalog.plans.discountPercent')}`, { exact: true }).fill(code === 'yearly' ? '12.50' : '10');
    }
    assert.equal(await key.getAttribute('dir'), 'ltr');
    await key.focus();
    await page.screenshot({ path: join(out, `${locale}-${width}-form.png`) });
    const bounds = await dialog.evaluate(e => ({ width: e.clientWidth, scroll: e.scrollWidth, left: e.getBoundingClientRect().left, right: e.getBoundingClientRect().right }));
    assert.ok(bounds.scroll <= bounds.width + 1 && bounds.left >= 0 && bounds.right <= width, JSON.stringify(bounds));
    await auditDialog();
    await dialog.getByRole('checkbox').last().scrollIntoViewIfNeeded();
    await auditDialog();
    await page.screenshot({ path: join(out, `${locale}-${width}-periods.png`) });
    await save.click(); await dialog.waitFor({ state: 'hidden' });
    const sent = writes.filter(w => w.path === '/platform/billing/plans').at(-1).body;
    assert.equal(sent.monthly_price, '82.50'); assert.equal(sent.billing_periods.length, 3);
    assert.equal(sent.display_name_ar, 'خطة إقليمية جديدة'); assert.equal(sent.trial_days, 7);
    const row = page.getByRole('row').filter({ hasText: locale === 'ar' ? sent.display_name_ar : sent.display_name });
    await row.getByText(t('billing.catalog.plans.configurationStates.MISSING_FEATURES'), { exact: true }).waitFor();
    await row.getByText(t('billing.catalog.plans.stripeSetupRequired'), { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
    await row.getByRole('button', { name: t('common.activate'), exact: true }).click();
    await dialog.getByRole('button', { name: t('common.activate'), exact: true }).click();
    await dialog.getByRole('alert').filter({ hasText: t('billing.catalog.plans.activationIncomplete') }).waitFor();
    await auditDialog();
    await dialog.getByRole('button', { name: t('common.cancel'), exact: true }).click();
    const nav = page.locator('.billing-catalog-tabs nav');
    await nav.getByRole('link', { name: t('billing.catalog.ownerNavigation.allowances'), exact: true }).click();
    await page.getByLabel(t('billing.catalog.fields.plan'), { exact: true }).selectOption(newKey);
    for (const code of [...numeric, 'market_intelligence']) {
      await page.getByLabel(t('billing.catalog.fields.feature'), { exact: true }).selectOption(code);
      if (numeric.includes(code)) await page.locator('.billing-catalog-toolbar input[type="number"]').fill('700');
      await page.getByRole('button', { name: t('billing.catalog.planFeatures.link'), exact: true }).click();
      await page.getByText(t('billing.catalog.planFeatures.linked'), { exact: true }).waitFor();
    }
    await nav.getByRole('link', { name: t('billing.catalog.tabs.plans'), exact: true }).click();
    await row.getByText(t('billing.catalog.plans.configurationStates.READY_TO_ACTIVATE'), { exact: true }).waitFor();
    await row.getByRole('button', { name: t('common.activate'), exact: true }).click();
    await dialog.getByRole('button', { name: t('common.activate'), exact: true }).click();
    await dialog.waitFor({ state: 'hidden' });
    await row.getByText(t('billing.catalog.plans.configurationStates.STRIPE_SETUP_REQUIRED'), { exact: true }).waitFor();
    assert.ok(await row.evaluate(e => e.getBoundingClientRect().height < 240), 'Long descriptions must not create screen-height table rows');
    await page.screenshot({ path: join(out, `${locale}-${width}-plans.png`), fullPage: true });
    assert.deepEqual(plans[0], seeded, 'Existing plan unchanged');
    assert.ok(writes.every(w => w.path === '/platform/billing/plans' || /^\/platform\/billing\/plans\/[^/]+\/(features|status)$/.test(w.path)));
    results.push({ locale, width, status: 'PASS', mode: 'Synthetic HTTP; real React components/adapters' });
    await context.close();
  }
  assert.deepEqual(pageErrors, []); assert.deepEqual(consoleIssues, []); assert.deepEqual(unexpected, []);
  console.log(`PASS Standard Plan creation UI: ${results.length} locale/viewport combinations`);
} finally {
  writeFileSync(join(out, 'results.json'), JSON.stringify({ results, consoleIssues, pageErrors, unexpected }, null, 2));
  await browser?.close(); await server.close();
}
