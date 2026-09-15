import httpClient from '../../../shared/lib/httpClient.js';
export const ADMIN_PREVIEW = import.meta.env.DEV && import.meta.env.VITE_ENABLE_PLATFORM_ADMIN_PREVIEW === 'true';
const preview = () => import('./previewAdapter.js');
const base = '/platform-admin';
// Proposed HTTP contract; the backend must authenticate and authorize every request.
// No fallback from a failed HTTP request to preview data.
export const platformAdminApi = {
  me: () => ADMIN_PREVIEW ? preview().then(m => m.previewAdapter.me()) : httpClient.get(`${base}/me`).then(r => r.data),
  list: (domain, params, signal) => ADMIN_PREVIEW ? preview().then(m => m.previewAdapter.list(domain, params)) : httpClient.get(`${base}/${domain}`, { params, signal }).then(r => r.data),
  detail: (domain, id, signal) => ADMIN_PREVIEW ? preview().then(m => m.previewAdapter.detail(domain, id)) : httpClient.get(`${base}/${domain}/${encodeURIComponent(id)}`, { signal }).then(r => r.data),
  mutate: (domain, id, action, payload) => ADMIN_PREVIEW ? preview().then(m => m.previewAdapter.mutate(domain, id, action, payload)) : httpClient.post(`${base}/${domain}/${encodeURIComponent(id || 'new')}/${action}`, payload).then(r => r.data),
  account: (action, payload) => ADMIN_PREVIEW ? preview().then(m => m.previewAdapter.account(action, payload)) : (action === 'sessions' ? httpClient.get(`${base}/me/sessions`) : httpClient.post(`${base}/me/${action}`, payload)).then(r => r.data),
  setPreviewRole: async role => { if (ADMIN_PREVIEW) (await preview()).setPreviewRole(role); },
};
