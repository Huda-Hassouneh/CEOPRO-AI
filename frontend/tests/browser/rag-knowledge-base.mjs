// Disposable PostgreSQL/MinIO/FastAPI + Chromium check for the Knowledge Base
// flow. The local environment has no configured LLM provider, so this verifies
// truthful provider-unavailable UX rather than claiming an answer/citation.
// Required: APP_URL, API_URL, E2E_EMAIL, E2E_PASSWORD, CHROMIUM_PATH.
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright-core';

const { APP_URL = 'http://127.0.0.1:5173', API_URL = 'http://127.0.0.1:18743',
  E2E_EMAIL: email, E2E_PASSWORD: password, E2E_LOCALE: locale = 'en' } = process.env;
if (!email || !password || !process.env.CHROMIUM_PATH) throw new Error('Missing disposable browser credentials or Chromium path.');

const temp = await mkdtemp(path.join(os.tmpdir(), 'keel-rag-browser-'));
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
try {
  const context = await browser.newContext({ viewport: { width: locale === 'ar' ? 390 : 1280, height: 900 } });
  await context.addInitScript((language) => localStorage.setItem('ceopro_locale', language), locale);
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(String(error)));
  await page.goto(`${APP_URL}/login`);
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.getByRole('button', { name: /sign in|log in|دخول|تسجيل الدخول/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
  const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session') || '{}').accessToken);
  const setup = await page.request.post(`${API_URL}/settings/company/onboarding/complete`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!setup.ok()) throw new Error(`Authorized onboarding completion returned ${setup.status()}`);
  await page.goto(`${APP_URL}/ai-advisor`);
  await page.getByRole('heading', { name: /knowledge base|قاعدة المعرفة/i }).waitFor({ timeout: 20000 });

  await page.locator('.rag-knowledge-panel > button').click({ force: true });
  const dialog = page.getByRole('dialog');
  await dialog.waitFor();
  const file = path.join(temp, 'returns-policy.txt');
  await writeFile(file, 'Returns are accepted within thirty calendar days when unused. Contact the service desk with the original order reference.');
  await dialog.locator('input[type="file"]').setInputFiles(file);
  await dialog.getByRole('button', { name: /upload document|رفع مستند/i }).click();
  await page.locator('.rag-document-row strong[title="returns-policy.txt"]').waitFor({ timeout: 30000 });
  await page.getByText(/ready for questions|جاهز.*الأسئلة/i).waitFor({ timeout: 10000 }).catch(() => {});

  const question = page.locator('.rag-chat-panel textarea');
  await question.fill('What is the return window stated in the uploaded policy?');
  await question.press('Enter');
  await page.getByRole('alert').waitFor({ timeout: 30000 });
  const alertText = (await page.getByRole('alert').innerText()).toLowerCase();
  if (!/not set up|not configured|غير مهيأ|غير معد|administrator|المسؤول/.test(alertText)) {
    throw new Error(`Expected truthful unavailable-model message, received: ${alertText}`);
  }
  const accessToken = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session') || '{}').accessToken);
  const sessionsResponse = await page.request.get(`${API_URL}/rag/sessions`, { headers: { Authorization: `Bearer ${accessToken}` } });
  const storedSessions = await sessionsResponse.json();
  if (!sessionsResponse.ok() || !(storedSessions.sessions || []).length) throw new Error('Failed user turn is not persisted in server-side conversation history.');
  await page.getByRole('button', { name: /history|السجل/i }).click();
  const history = page.getByRole('menu');
  await history.waitFor();
  await history.locator('.rag-session-history__item').first().waitFor({ timeout: 10000 });
  if (!(await history.getByRole('menuitem').count())) throw new Error('Failed question did not remain in persisted conversation history.');
  if (!(await history.innerText()).includes('What is the return window')) throw new Error('Conversation history did not identify the saved question.');
  const direction = await page.locator('.rag-assistant-page').getAttribute('dir');
  if (direction !== (locale === 'ar' ? 'rtl' : 'ltr')) throw new Error(`Unexpected direction ${direction} for ${locale}`);
  if (pageErrors.length) throw new Error(`Browser errors: ${pageErrors.join('; ')}`);
  const result = await page.request.get(`${API_URL}/rag/documents`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!result.ok()) throw new Error(`RAG document API returned ${result.status()}`);
  const documents = (await result.json()).documents;
  const uploaded = documents.find((doc) => doc.file_name === 'returns-policy.txt');
  if (!uploaded || uploaded.searchable !== true || uploaded.status !== 'ready') throw new Error('Uploaded document was not persisted as searchable evidence.');
  console.log(`RAG browser flow (${locale}): authenticated, uploaded/indexed document, displayed truthful model-unavailable state, history and direction verified`);
} finally {
  await browser.close();
  await rm(temp, { recursive: true, force: true });
}
