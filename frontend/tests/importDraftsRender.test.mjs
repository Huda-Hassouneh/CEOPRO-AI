import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createServer } from 'vite';
import { useAuthStore } from '../src/features/auth/store/authStore.js';

let vite;
test.before(async () => { vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' }); });
test.after(async () => { await vite.close(); });

test('import review panel renders real draft rows and explicit review-only boundary accessibly', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(['import-drafts', 0, ''], { items: [{
    batch_id: 'b-1', created_at: '2026-10-21T10:00:00Z', source_name: 'Manual upload', category: 'invoice',
    invalid_row_count: 1, review_required_row_count: 1, review_status: 'review_required', posting_status: 'not_committed',
  }], limit: 10, offset: 0 });
  useAuthStore.setState({ roles: ['OWNER'] });
  const { ImportDraftsPanel } = await vite.ssrLoadModule('/src/features/data-ingestion/components/ImportDraftsPanel.jsx');
  const { translate } = await vite.ssrLoadModule('/src/shared/lib/i18n.js');
  const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client },
    React.createElement(ImportDraftsPanel, { t: (key, values) => translate('en', key, values), locale: 'en' }),
  ));
  assert.match(html, /Import review/);
  assert.match(html, /Approval records your decision; it does not necessarily post data to KEEL/);
  assert.match(html, /Invoices/);
  assert.match(html, /not_committed/);
  assert.match(html, /Preview/);
  assert.match(html, /role="region" aria-label="Import drafts" tabindex="0"/);
  assert.match(html, /<table class="connect-data-table import-drafts-list-table">/);
  useAuthStore.setState({ roles: [] });
  client.clear();
});
