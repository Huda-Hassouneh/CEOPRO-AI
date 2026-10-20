import httpClient from '../../../shared/lib/httpClient.js';

// Operator-only service setup (backend/src/ai/routers/operator.py). Status and a connection test; no key value ever travels here.
export const operatorApi = {
  isOperator: async () => (await httpClient.get('/operator/me')).data.is_operator === true,
  providers: async () => (await httpClient.get('/operator/providers')).data.providers,
  test: async (provider) => (await httpClient.post(`/operator/providers/${encodeURIComponent(provider)}/test`)).data.result,
};
