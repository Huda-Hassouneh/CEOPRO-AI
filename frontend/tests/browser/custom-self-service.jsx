// Disposable acceptance shell. Uses the production page/API client unchanged.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { I18nProvider } from '../../src/app/providers/I18nProvider.jsx';
import { loadLocale } from '../../src/shared/lib/i18n.js';
import { CustomPlanBuilderPage } from '../../src/features/billing/pages/CustomPlanBuilderPage.jsx';
await loadLocale(localStorage.getItem('ceopro_locale') || 'en');
createRoot(document.getElementById('root')).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><I18nProvider><CustomPlanBuilderPage /></I18nProvider></MemoryRouter>
  </QueryClientProvider>
);
