import React from 'react';
import {createRoot} from 'react-dom/client';
import {MemoryRouter} from 'react-router-dom';
import {I18nProvider} from '../src/app/providers/I18nProvider.jsx';
import {DashboardHomePage} from '../src/features/dashboard/pages/DashboardHomePage.jsx';
export function mountDashboardEdgeCase(target) {
 createRoot(target).render(<I18nProvider><MemoryRouter><DashboardHomePage forecast={null} sentiment={{status:'UNKNOWN',evidence_id:'test',sample_size:{status:'insufficient',minimum_required:30}}} competitiveness={{value:null,missing_factors:['price']}} /></MemoryRouter></I18nProvider>);
}
