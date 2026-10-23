import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFile } from 'node:fs/promises';
import { createServer } from 'vite';

let vite;
test.before(async () => { vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' }); });
test.after(async () => { await vite.close(); });

async function renderError(locale, busy = false) {
  const translations = JSON.parse(await readFile(new URL(`../src/assets/locales/${locale}.json`, import.meta.url), 'utf8'));
  const { AlertsLoadError } = await vite.ssrLoadModule('/src/features/alerts/AlertsLoadError.jsx');
  const t = (key) => key.split('.').reduce((value, part) => value?.[part], translations) || key;
  return renderToStaticMarkup(React.createElement(AlertsLoadError, { onRetry() {}, busy, t }));
}

test('alert load errors expose a localized retry action and disable it while refreshing', async () => {
  const english = await renderError('en');
  assert.match(english, /role="alert"/);
  assert.match(english, /Alerts couldn&#x27;t be loaded/);
  assert.match(english, />Try again<\/button>/);

  const arabic = await renderError('ar');
  assert.match(arabic, /تعذر تحميل التنبيهات/);
  assert.match(arabic, /إعادة المحاولة/);
  assert.match(await renderError('ar', true), /disabled=""/);
});
