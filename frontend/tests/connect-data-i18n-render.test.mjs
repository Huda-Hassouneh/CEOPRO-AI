import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { I18nProvider } from '../src/app/providers/I18nProvider.jsx';
import { translate } from '../src/shared/lib/i18n.js';
import { useAuthStore } from '../src/features/auth/store/authStore.js';
import { ConnectDataPage } from '../src/features/data-connections/pages/ConnectDataPage.jsx';
import { IngestionJobStatusTable } from '../src/features/data-ingestion/components/IngestionJobStatusTable.jsx';
import { StagingRowReviewGrid } from '../src/features/data-ingestion/components/StagingRowReviewGrid.jsx';
import { StructuredImportReview } from '../src/features/data-ingestion/components/StructuredImportReview.jsx';
import { activityTypeLabel, activityName, dataCategoryLabel, importSheetLabel, jobErrorMessage,
  rowValidationMessage, storeErrorMessage, connectionStatusLabel, dataConnectionErrorMessage,
} from '../src/features/data-connections/utils/connectionPresentation.js';

const h = React.createElement;
const source = { id: 'store', name: { en: 'pc-store.example', ar: 'pc-store.example' }, provider: 'shopify',
  type: 'website', status: 'synced', actions: ['details', 'syncNow', 'connectStore', 'pause', 'disconnect'],
  categories: ['Products', 'Sales', 'Inventory', 'Invoices'], lastUpdatedAt: null, recordCount: 120 };
const activity = { id: 'job', source: source.name, name: 'Sync - pc-store.example', type: 'Website', status: 'Completed', date: '2026-10-18T12:00:00Z' };
const data = { connectedSources: [source], recentImports: [activity], availableSourceTypes: [],
  sourceCapacity: { currentUsage: 1, remaining: 4, limit: 5, included: true, isUnlimited: false } };

for (const locale of ['en', 'ar']) {
  const t = (key, values) => translate(locale, key, values);
  test(`${locale}: Connect Data renders real dynamic actions, activity types and names without unresolved keys`, () => {
    const previousWindow = globalThis.window;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    try {
      globalThis.window = { localStorage: { getItem: () => locale } };
      // Zustand uses its initial snapshot during server rendering.
      client.setQueryData(['data-connection', useAuthStore.getInitialState().tenantId], data);
      client.setQueryData(['subscription', 'usage'], { entitlements: [
        { feature_code: 'document_extraction', is_unlimited: true },
      ] });
      const html = renderToStaticMarkup(h(QueryClientProvider, { client }, h(I18nProvider, null, h(ConnectDataPage))));
      for (const key of ['connectData.page.title', 'connectData.actions.syncNow', 'connectData.actions.connectStore',
        'connectData.categories.products', 'connectData.fileTypes.website']) assert.ok(html.includes(t(key)), key);
      assert.ok(html.includes(t('connectData.activity.syncName', { name: 'pc-store.example' })));
      assert.ok(html.includes(`dir="${locale === 'ar' ? 'rtl' : 'ltr'}"`));
      assert.doesNotMatch(html, /connectData\.|storeConnection\.|Sync - pc-store/);
      assert.ok(html.includes('pc-store.example'));
    } finally {
      client.clear();
      if (previousWindow === undefined) delete globalThis.window; else globalThis.window = previousWindow;
    }
  });

  test(`${locale}: job details and staged validation errors use locale messages`, () => {
    const job = { status: 'FAILED', sourceName: 'sales.csv', rowsProcessed: 2, rowsFailed: 1,
      rowsPartial: 0, processingAttempts: 1, error: 'STORE_SHOPIFY_QUERY_ERROR', createdAt: '2026-10-18T12:00:00Z' };
    const html = renderToStaticMarkup(h(React.Fragment, null,
      h(IngestionJobStatusTable, { job, t, formatDate: () => '2026-10-18' }),
      h(StagingRowReviewGrid, { t, rows: [{ id: '1', status: 'invalid', payload: { sku: 'PC-001' },
        errors: JSON.stringify({ quantity: 'quantity must be a positive integer.' }) }] })));
    for (const key of ['connectData.statuses.failed', 'storeConnection.errors.STORE_SHOPIFY_QUERY_ERROR',
      'connectData.job.rowStatuses.invalid', 'connectData.review.issues.quantity']) assert.ok(html.includes(t(key)), key);
    assert.doesNotMatch(html, /connectData\.|storeConnection\.|quantity must be a positive/);
    assert.ok(html.includes('PC-001') && html.includes('sales.csv'));
    assert.equal(jobErrorMessage('2 invalid row(s); 3 partial row(s) require review.', t),
      t('connectData.job.reviewSummary', { invalid: 2, partial: 3 }));
  });

  test(`${locale}: import review translates template sheet names while retaining product names`, () => {
    const preview = { matches: [], issues: [{ sheet: 'Invoice Items', row: 2, message: 'quantity must be a positive integer.' }],
      sheets: ['Invoices', 'Invoice Items'], counts: { invoices: 1, items: 1, inventory: 0, matched: 1, needsAttention: 0 }, canCreateProducts: false };
    const html = renderToStaticMarkup(h(StructuredImportReview, { preview, choices: {}, review: null,
      busy: false, locale, t, onCancel() {}, onReview() {} }));
    assert.ok(html.includes(t('connectData.review.sheetNames.invoiceItems')));
    assert.ok(html.includes(t('connectData.review.issues.quantity')));
    assert.equal(importSheetLabel('Custom Sheet', t), 'Custom Sheet');
  });

  test(`${locale}: future enums and unknown errors have translated fallbacks; user content is preserved`, () => {
    assert.equal(connectionStatusLabel('FUTURE_STATUS', t), t('connectData.statuses.unknown'));
    assert.equal(activityTypeLabel('Business System', t), t('connectData.fileTypes.businesssystem'));
    assert.equal(activityTypeLabel('new-provider', t), t('connectData.fileTypes.unknown'));
    assert.equal(activityName({ name: 'Sync - inventory.csv', type: 'File' }, locale, t), 'Sync - inventory.csv');
    assert.equal(dataCategoryLabel('My custom category', locale, t), 'My custom category');
    assert.equal(storeErrorMessage({ code: 'STORE_SHOPIFY_SCOPES_REQUIRED' }, t), t('storeConnection.errors.STORE_SHOPIFY_SCOPES_REQUIRED'));
    assert.equal(storeErrorMessage({ code: 'STORE_FUTURE_ERROR' }, t), t('storeConnection.errors.STORE_SERVICE_UNAVAILABLE'));
    assert.equal(dataConnectionErrorMessage({ response: { status: 403, data: { code: 'FORBIDDEN', message: 'Backend English sentence' } } }, t), t('apiErrors.FORBIDDEN'));
    assert.equal(rowValidationMessage('Unknown server validation message', t), t('connectData.job.unknownError'));
    assert.equal(rowValidationMessage(null, t), '—');
  });
}
