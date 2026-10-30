// Production owner Billing page; identity is injected only in the disposable API.
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
await loadLocale(localStorage.getItem('ceopro_locale') || 'en');
createRoot(document.getElementById('root')).render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>
  <MemoryRouter initialEntries={['/admin/billing?tab=plans']}><I18nProvider>
    <BillingCatalogPage api={platformBillingCatalogApi} platformMode canManage canManagePricing />
  </I18nProvider></MemoryRouter>
</QueryClientProvider>);
