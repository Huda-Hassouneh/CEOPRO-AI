// Browser fixture: production components and API adapter; synthetic HTTP in the runner.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { I18nProvider } from '../../src/app/providers/I18nProvider.jsx';
import { loadLocale } from '../../src/shared/lib/i18n.js';
import { BillingCatalogPage } from '../../src/features/billing/pages/BillingCatalogPage.jsx';
import { platformBillingCatalogApi } from '../../src/features/platform/platformBillingCatalogApi.js';
import '../../src/styles/globals.css';
import '../../src/styles/apex-theme.css';
import '../../src/styles/apex-components.css';
import '../../src/styles/apex-motion.css';
import '../../src/styles/keel-glass.css';
import '../../src/features/platform-admin/styles/PlatformAdmin.css';

await loadLocale(localStorage.getItem('ceopro_locale') || 'en');
const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
createRoot(document.getElementById('root')).render(
  <QueryClientProvider client={client}><MemoryRouter initialEntries={['/admin/billing?tab=plans']}>
    <I18nProvider><main className="pa-shell" style={{ padding: 24 }}>
      <BillingCatalogPage api={platformBillingCatalogApi} platformMode canManage canManagePricing />
    </main></I18nProvider>
  </MemoryRouter></QueryClientProvider>
);
