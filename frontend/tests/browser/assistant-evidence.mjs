// The assistant when the server could not write an answer (no model price, no
// key): the reply is shown from the cited evidence, with the "shown without
// AI writing" banner and, when the cause is a missing set-up, a note that tells the
// person to ask their administrator. The /rag/query reply is served by the
// test, so no language model is called. Needs the app running and any account.
//
//   APP_URL=http://localhost:5173 E2E_EMAIL=... E2E_PASSWORD=... [E2E_LOCALE=ar] \
//   [CHROMIUM_PATH=/path/to/chrome] node tests/browser/assistant-evidence.mjs
import { chromium } from 'playwright-core';

const BASE = process.env.APP_URL || 'http://localhost:5173';
const { E2E_EMAIL: email, E2E_PASSWORD: password } = process.env;
const locale = process.env.E2E_LOCALE || 'en';
if (!email || !password) {
  console.error('Set E2E_EMAIL and E2E_PASSWORD to an account that has finished setup.');
  process.exit(2);
}

const reply = (writing) => ({
  session_id: '11111111-1111-1111-1111-111111111111',
  answer: 'You have 10 products.¹',
  answer_mode: 'evidence',
  answer_summary: { text: 'You have 10 products.', refs: [1], claims: [{ text: 'You have 10 products.', kind: 'fact', refs: [1], verified: true, notes: [] }] },
  answer_blocks: [
    { type: 'paragraph', claims: [{ text: 'The writing service is unavailable, so this is the evidence KEEL found:', kind: 'general', refs: [], verified: true, notes: [] }] },
    { type: 'list', ordered: false, items: [[{ text: 'Your product catalogue: You have 10 products.', kind: 'fact', refs: [1], verified: true, notes: [] }]] },
  ],
  references: [{ n: 1, evidence_id: 'E1', kind: 'company_record', title: 'Your product catalogue', excerpt: 'You have 10 products.', route: '/products', used_as: ['supports_fact'], limitations: [] }],
  evidence_status: [{ need: 'answer_writing', status: writing }],
  follow_up_questions: [],
  calculations: [],
});

const failures = [];
const check = (condition, message) => { if (!condition) failures.push(message); };
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const context = await browser.newContext({ viewport: { width: Number(process.env.E2E_WIDTH || 1280), height: 900 } });
await context.addInitScript((l) => localStorage.setItem('ceopro_locale', l), locale);
const page = await context.newPage();
page.on('pageerror', (error) => failures.push(`page error: ${String(error).slice(0, 200)}`));

let writing = 'not_configured';
await page.route('**/rag/query*', (route) => route.fulfill({
  status: 200, contentType: 'application/json', body: JSON.stringify(reply(writing)),
}));

await page.goto(`${BASE}/login`);
await page.fill('input[type="email"]', email);
await page.fill('input[type="password"]', password);
await page.click('button[type="submit"]');
await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
await page.goto(`${BASE}/ai-advisor`, { waitUntil: 'domcontentloaded' });
const composer = page.locator('.rag-chat-panel textarea');
await composer.waitFor({ timeout: 20000 });

async function ask(text) {
  const before = await page.locator('.rag-message.is-assistant').count();
  await composer.fill(text);
  await composer.press('Enter');
  await page.waitForFunction((n) => document.querySelectorAll('.rag-message.is-assistant').length > n && !document.querySelector('.rag-generating'),
    before, { timeout: 30000 });
  return page.locator('.rag-message.is-assistant').last();
}

const configured = await ask('How many products do I have?');
check(await configured.locator('.rag-evidence-note').count() === 1, 'no "shown without AI writing" banner');
check(await configured.locator('.rag-cite button').count() > 0, 'the evidence answer has no reference marker');
// The short answer is read first; the evidence behind it is one disclosure away, and its label follows its state.
check((await configured.locator('.rag-answer-summary').textContent().catch(() => '')).includes('10 products'), 'no summary above the evidence');
const toggle = configured.locator('.rag-answer-details > summary');
check(await configured.locator('.rag-answer-details li').first().isHidden(), 'the evidence list is not collapsed behind the summary');
const closedLabel = await toggle.textContent();
await toggle.click();
check(await configured.locator('.rag-answer-details li').first().isVisible(), 'the toggle does not reveal the full answer');
const relabelled = await page.waitForFunction(
  (label) => [...document.querySelectorAll('.rag-answer-details > summary')].some((el) => el.textContent !== label),
  closedLabel, { timeout: 3000 }).then(() => true, () => false);
check(relabelled, 'the toggle label does not change when it opens');
const adminNote = (await configured.locator('.rag-status-notes').textContent().catch(() => '')) || '';
check(/administrator|مسؤول/.test(adminNote), `no "ask your administrator" note when answer writing is not configured: "${adminNote}"`);

writing = 'provider_busy';
const busy = await ask('And their prices?');
check(await busy.locator('.rag-evidence-note').count() === 1, 'the banner is missing when the provider is busy');
const busyNote = (await busy.locator('.rag-status-notes').textContent().catch(() => '')) || '';
check(!/administrator|مسؤول/.test(busyNote), 'a temporary provider problem must not tell people to contact an administrator');

const text = await page.locator('.rag-chat-panel').innerText();
check(!/ragAssistant\.[\w.]+/.test(text), 'untranslated keys on the page');
await browser.close();

if (failures.length) {
  console.error(`assistant evidence mode (${locale}): ${failures.length} problem(s)\n- ${failures.join('\n- ')}`);
  process.exit(1);
}
console.log(`assistant evidence mode (${locale}): banner, references and administrator note behave`);
