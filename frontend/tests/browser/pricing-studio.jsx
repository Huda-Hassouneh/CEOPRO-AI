// Production owner Billing page; identity is injected only in the disposable API.
import React from 'react';
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { I18nProvider, useI18n } from '../../src/app/providers/I18nProvider.jsx';
import { loadLocale } from '../../src/shared/lib/i18n.js';
import { BillingCatalogPage } from '../../src/features/billing/pages/BillingCatalogPage.jsx';
import { QuoteReviewModal } from '../../src/features/billing/components/CustomPlanQuoteManager.jsx';
import { platformBillingCatalogApi } from '../../src/features/platform/platformBillingCatalogApi.js';
import '../../src/styles/globals.css';
import '../../src/styles/apex-theme.css';
import '../../src/styles/apex-components.css';
await loadLocale(localStorage.getItem('ceopro_locale') || 'en');
const client = new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}});
client.setQueryData(['owner-quote-review','synthetic-review'], {data:{
  id:'synthetic-review',name:'Synthetic review',status:'submitted',currency:'JOD',
  pricingSnapshot:{reviewDecision:{required:true,reasons:['QUOTA_ABOVE_AUTOMATIC_LIMIT:connected_data_sources']},
    commercial:{amount:'300.00',currency:'JOD'},payment:{amount:'423.13',currency:'USD'},
    fx:{rate:'0.709',source:'synthetic fixture',version:'fixture-v1'}},
}});
function ReviewFixture() {
  const [open,setOpen]=useState(false);
  const {t,locale}=useI18n();
  if (!window.location.search.includes('owner_quote_fixture=1')) return null;
  return <><button type="button" data-testid="synthetic-review" onClick={()=>setOpen(true)}>Open synthetic review</button>
    {open && <QuoteReviewModal quote={{id:'synthetic-review'}} onClose={()=>setOpen(false)}
      api={{getCustomPlanQuote:()=>Promise.reject(new Error('Fixture must not request quote API'))}} t={t} locale={locale}/>}</>;
}
createRoot(document.getElementById('root')).render(<QueryClientProvider client={client}>
  <MemoryRouter initialEntries={['/admin/billing?tab=plans']}><I18nProvider>
    <ReviewFixture />
    <BillingCatalogPage api={platformBillingCatalogApi} platformMode canManage canManagePricing />
  </I18nProvider></MemoryRouter>
</QueryClientProvider>);
