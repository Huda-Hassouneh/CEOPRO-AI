// Offline browser fixture: production quote page and dashboard setup guard.
// Subscription/quote responses are synthetic; no payment provider or DB is used.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route, Link } from 'react-router-dom';
import { I18nProvider } from '../../src/app/providers/I18nProvider.jsx';
import { loadLocale } from '../../src/shared/lib/i18n.js';
import { useAuthStore } from '../../src/features/auth/store/authStore.js';
import { useSubscription } from '../../src/features/billing/hooks/useSubscription.js';
import { CustomPlanQuotePage } from '../../src/features/billing/pages/CustomPlanQuotePage.jsx';
import { SetupGate } from '../../src/app/router/SetupGate.jsx';
import '../../src/styles/globals.css';
import '../../src/styles/apex-theme.css';
import '../../src/styles/apex-components.css';
import '../../src/styles/keel-glass.css';

await loadLocale(localStorage.getItem('ceopro_locale') || 'en');
useAuthStore.setState({ tenantId: 'synthetic-tenant', user: { id: 'synthetic-user' } });
const quotePath = '/billing/custom-plan/quotes/synthetic-quote';
function Dashboard() {
  const { data } = useSubscription('synthetic-tenant');
  return <div data-testid="dashboard">{data?.planId}:{data?.limits?.products}<Link to={quotePath}>Quote</Link></div>;
}
createRoot(document.getElementById('root')).render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[new URLSearchParams(window.location.search).get('route') === 'dashboard' ? '/dashboard' : quotePath]}><I18nProvider><Routes>
      <Route path="/billing/custom-plan/quotes/:quoteId" element={<CustomPlanQuotePage />} />
      <Route path="/dashboard" element={<SetupGate><Dashboard /></SetupGate>} />
      <Route path="*" element={<div data-testid="safe-navigation">No protected access granted</div>} />
    </Routes></I18nProvider></MemoryRouter>
  </QueryClientProvider>
);
