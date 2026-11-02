// Real onboarding components; HTTP boundaries are doubled by the browser test.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { I18nProvider } from '../../src/app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../src/features/auth/store/authStore.js';
import { OnboardingGate } from '../../src/features/onboarding/components/OnboardingGate.jsx';
import { OnboardingPlanSelectionPage } from '../../src/features/billing/pages/OnboardingPlanSelectionPage.jsx';
import { OnboardingPaymentPage } from '../../src/features/billing/pages/OnboardingPaymentPage.jsx';
import { SetupGate } from '../../src/app/router/SetupGate.jsx';
import '../../src/styles/globals.css';
import '../../src/styles/apex-theme.css';

useAuthStore.setState({tenantId:'synthetic-tenant',user:{id:'synthetic-user'},isHydrated:true});
const entry=new URLSearchParams(window.location.search).get('entry')||'/onboarding/plan';
createRoot(document.getElementById('root')).render(
  <QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>
    <I18nProvider><MemoryRouter initialEntries={[entry]}><Routes>
      <Route path="/onboarding/plan" element={<OnboardingGate step={5}><OnboardingPlanSelectionPage/></OnboardingGate>}/>
      <Route path="/onboarding/plan/payment" element={<OnboardingGate><OnboardingPaymentPage/></OnboardingGate>}/>
      <Route path="/onboarding/connect-data" element={<h1>Connections fixture</h1>}/>
      <Route path="/onboarding" element={<h1>Onboarding required</h1>}/>
      <Route path="/dashboard" element={<SetupGate><h1>Dashboard fixture</h1></SetupGate>}/>
    </Routes></MemoryRouter></I18nProvider>
  </QueryClientProvider>,
);
