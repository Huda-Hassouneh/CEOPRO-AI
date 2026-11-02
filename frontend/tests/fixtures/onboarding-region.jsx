// Controlled UI fixture only: no authentication/customer or production DB writes.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route, Link } from 'react-router-dom';
import { I18nProvider } from '../../src/app/providers/I18nProvider.jsx';
import { OnboardingGate } from '../../src/features/onboarding/components/OnboardingGate.jsx';
import { OnboardingRegionalPreferencesPage } from '../../src/features/onboarding/pages/OnboardingRegionalPreferencesPage.jsx';
import '../../src/styles/globals.css';
import '../../src/styles/apex-theme.css';
import '../../src/features/onboarding/styles/Onboarding.css';

createRoot(document.getElementById('root')).render(
  <QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}>
    <I18nProvider><MemoryRouter initialEntries={['/onboarding/region']}><Routes>
      <Route path="/onboarding/region" element={<OnboardingGate step={1}><OnboardingRegionalPreferencesPage/></OnboardingGate>}/>
      <Route path="/onboarding/industry" element={<><h1>Industry fixture</h1><Link to="/onboarding/region">Back to region</Link></>}/>
    </Routes></MemoryRouter></I18nProvider>
  </QueryClientProvider>,
);
