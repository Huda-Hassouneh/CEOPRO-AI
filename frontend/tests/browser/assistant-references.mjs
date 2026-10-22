// Asks the assistant a real question and checks its claim-level references:
// numbered markers beside the claims, a reference panel that opens on click
// with the source's title and supporting excerpt, closes with Escape and
// returns focus to the marker, follows the page direction (right-to-left in
// Arabic) and passes the axe-core WCAG 2.1 A/AA audit. Needs the app running
// with a configured language model and an account that has data.
//
//   APP_URL=http://localhost:5173 E2E_EMAIL=... E2E_PASSWORD=... [E2E_LOCALE=ar] [E2E_QUESTION=...] \
//   [CHROMIUM_PATH=/path/to/chrome] node tests/browser/assistant-references.mjs
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { chromium } from 'playwright-core';

const require = createRequire(import.meta.url);
const AXE = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const BASE = process.env.APP_URL || 'http://localhost:5173';
const { E2E_EMAIL: email, E2E_PASSWORD: password } = process.env;
const locale = process.env.E2E_LOCALE || 'en';
const question = process.env.E2E_QUESTION
  || (locale === 'ar' ? 'كيف كانت مبيعاتي في آخر 30 يوم؟' : 'How were my sales in the last 30 days?');
if (!email || !password) {
  console.error('Set E2E_EMAIL and E2E_PASSWORD to an account that has finished setup.');
  process.exit(2);
}

const failures = [];
const check = (condition, message) => { if (!condition) failures.push(message); };
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const context = await browser.newContext({ viewport: { width: Number(process.env.E2E_WIDTH || 1280), height: 900 } });
await context.addInitScript((l) => localStorage.setItem('ceopro_locale', l), locale);
const page = await context.newPage();
page.on('pageerror', (error) => failures.push(`page error: ${String(error).slice(0, 200)}`));

await page.goto(`${BASE}/login`);
await page.fill('input[type="email"]', email);
await page.fill('input[type="password"]', password);
await page.click('button[type="submit"]');
await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
await page.goto(`${BASE}/ai-advisor`, { waitUntil: 'domcontentloaded' });
const composer = page.locator('.rag-chat-panel textarea');
await composer.waitFor({ timeout: 20000 });
await composer.fill(question);
await composer.press('Enter');
const answer = page.locator('.rag-message.is-assistant').last();
// A long answer opens on its short summary, with the full answer in a collapsed disclosure.
await answer.locator('.rag-answer-summary, .rag-answer-copy').first().waitFor({ timeout: 120000 });
await page.waitForFunction(() => !document.querySelector('.rag-generating'), null, { timeout: 120000 });
const disclosure = answer.locator('.rag-answer-details > summary');
if (await disclosure.count()) {
  check(await answer.locator('.rag-answer-details .rag-answer-copy').isHidden(), 'the full answer is not collapsed behind its summary');
  await disclosure.click();
  check(await answer.locator('.rag-answer-details .rag-answer-copy').isVisible(), 'the full answer does not open');
}

const markers = answer.locator('.rag-cite button');
const markerCount = await markers.count();
check(markerCount > 0, 'the answer has no reference markers beside its claims');
if (markerCount > 0) {
  const marker = markers.first();
  const label = await marker.getAttribute('aria-label');
  check(Boolean(label) && !label.includes('ragAssistant.'), `marker label is not translated: ${label}`);
  await marker.click();
  const panel = page.locator('.rag-reference-panel[role="dialog"]');
  await panel.waitFor({ timeout: 5000 });
  const title = (await panel.locator('h3').textContent())?.trim();
  check(Boolean(title), 'the reference panel has no title');
  const excerpt = (await panel.locator('blockquote').textContent().catch(() => ''))?.trim();
  check(Boolean(excerpt), 'the reference panel shows no supporting excerpt');
  const focused = await page.evaluate(() => document.activeElement?.tagName);
  check(focused === 'H3', `focus did not move to the panel heading (it is on ${focused})`);
  check((await panel.getAttribute('dir')) === (locale === 'ar' ? 'rtl' : 'ltr'), 'the panel does not follow the page direction');
  const box = await panel.boundingBox();
  const viewport = page.viewportSize();
  check(box && box.x >= 0 && box.x + box.width <= viewport.width + 1, 'the panel is outside the screen');
  const untranslated = await panel.evaluate((element) => element.innerText.match(/ragAssistant\.[\w.]+/g));
  check(!untranslated, `untranslated text in the panel: ${untranslated}`);
  await page.addScriptTag({ content: AXE });
  const violations = await page.evaluate(async () => {
    const result = await window.axe.run('.rag-reference-panel', { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } });
    return result.violations.map((v) => `${v.id}: ${v.help}`);
  });
  check(violations.length === 0, `accessibility: ${violations.join('; ')}`);
  await page.keyboard.press('Escape');
  await panel.waitFor({ state: 'detached', timeout: 5000 }).catch(() => failures.push('Escape did not close the panel'));
  const restored = await page.evaluate(() => document.activeElement?.closest('.rag-cite') !== null);
  check(restored, 'focus did not return to the reference marker');
}
await browser.close();

if (failures.length) {
  console.error(`assistant references (${locale}): ${failures.length} problem(s)\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`assistant references (${locale}): ${markerCount} markers, panel opens, closes and passes the audit`);
