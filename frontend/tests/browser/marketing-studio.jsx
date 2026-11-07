// Disposable acceptance shell for the Marketing Studio: the production page,
// API client and styles, unchanged, with no login (the API is answered by
// the browser test - see marketing-studio-ui.mjs).
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import '../../src/styles/globals.css';
import '../../src/styles/apex-theme.css';
import '../../src/styles/apex-components.css';
import '../../src/styles/apex-motion.css';
import '../../src/styles/keel-glass.css';
import { I18nProvider } from '../../src/app/providers/I18nProvider.jsx';
import { loadLocale } from '../../src/shared/lib/i18n.js';
import MarketingStudioPage from '../../src/features/marketing/pages/MarketingStudioPage.jsx';

await loadLocale(localStorage.getItem('ceopro_locale') || 'en');
createRoot(document.getElementById('root')).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[`/marketing${window.location.search}`]}>
      <I18nProvider><MarketingStudioPage /></I18nProvider>
    </MemoryRouter>
  </QueryClientProvider>,
);
