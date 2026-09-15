import { connectDataMockData } from '../mocks/connectDataMockData.js';

const previewDelay = (result) => new Promise((resolve) => globalThis.setTimeout(() => resolve(result), 450));

export const dataConnectionsApi = Object.freeze({
  // Future: GET /companies/:companyId/data-connections
  list: async () => ({ ...connectDataMockData, preview: true }),
  connectGoogleAnalytics: (payload = {}) => previewDelay({
    ok: false,
    operation: 'connectGoogleAnalytics',
    payload,
    preview: true,
    connected: false,
    status: 'error',
    errorCode: 'oauth_not_configured',
  }),
  configureWebsite: (payload) => previewDelay({
    ok: Boolean(payload?.url),
    operation: 'configureWebsite',
    payload,
    preview: true,
    connected: Boolean(payload?.url),
    status: payload?.url ? 'connected' : 'error',
  }),
  prepareDatabase: (payload) => previewDelay({ ok: true, operation: 'prepareDatabase', payload, preview: true, connected: false, status: 'not-connected' }),
  // Future management endpoints. No local state is changed while unavailable.
  sync: (sourceId) => previewDelay({ ok: false, sourceId, available: false, operation: 'sync' }),
  reconnect: (sourceId) => previewDelay({ ok: false, sourceId, available: false, operation: 'reconnect' }),
});
