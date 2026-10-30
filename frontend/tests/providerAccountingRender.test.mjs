import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createServer } from 'vite';

let vite, ProviderAccounting, I18nProvider;
test.before(async () => {
  vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
  ({ ProviderAccounting } = await vite.ssrLoadModule('/src/features/platform/ProviderAccounting.jsx'));
  ({ I18nProvider } = await vite.ssrLoadModule('/src/app/providers/I18nProvider.jsx'));
});
test.after(async () => { await vite.close(); });
function render(client) {
  return renderToStaticMarkup(React.createElement(QueryClientProvider, { client },
    React.createElement(I18nProvider, null, React.createElement(ProviderAccounting, { canManage: true }))));
}
const key = ['platform', undefined, 'provider-accounting'];
test('accounting page renders loading, safe failure, real schedules and missing prices', () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryOnMount: false, staleTime: Infinity } } });
  assert.match(render(client), /role="status" aria-label="Loading/);
  const query = client.getQueryCache().find({ queryKey: key });
  query.setState({ status: 'error', error: new Error('internal-secret-fixture'), fetchStatus: 'idle' });
  const failed = render(client);
  assert.match(failed, /Provider accounting could not be loaded/);
  assert.doesNotMatch(failed, /internal-secret-fixture/);
  client.setQueryData(key, { schedules: [{ budget_kind: 'data', provider: 'brave_search', operation: 'search', unit: 'request', unit_cost_usd: '0.030000000000', cost_is_final: true, charged_on_failure: false, source: 'Verified invoice' }] });
  const html = render(client);
  assert.match(html, /0\.030000000000/);
  assert.match(html, /Verified invoice/);
  assert.match(html, /Missing price/);
  assert.match(html, /google_cse/);
  assert.match(html, /tavily/);
  assert.match(html, /Configured/);
  assert.match(html, /Add accounting schedule/);
  client.clear();
});
test('accounting labels are at the billing root in English and readable Arabic', () => {
  for (const locale of ['en', 'ar']) {
    const messages = JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`, import.meta.url), 'utf8'));
    assert.ok(messages.billing.providerAccounting.title);
    if (locale === 'ar') for (const value of Object.values(messages.billing.providerAccounting)) assert.match(value, /[\u0600-\u06ff]/);
  }
});
