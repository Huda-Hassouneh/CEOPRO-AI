import httpClient from '../../../shared/lib/httpClient.js';
import { toSession } from '../../auth/api/authHttpAdapter.js';

// One login, several companies (backend/src/ai/routers/auth.py): list them,
// open another, or create a new one. Switching returns a session for the
// other company; nothing is shared between companies.
export const workspacesApi = {
  list: async () => (await httpClient.get('/auth/workspaces')).data,
  switchTo: async (tenantId) => toSession((await httpClient.post('/auth/workspaces/switch', { tenant_id: tenantId })).data),
  create: async ({ name, country, currency }) => toSession((await httpClient.post('/auth/workspaces', {
    business_name: name, country_code: country, primary_currency: currency,
  })).data),
};
