import httpClient from "../../../shared/lib/httpClient.js";
import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import { previewAdapter, setPreviewRole } from "./previewAdapter.js";

export const ADMIN_PREVIEW = UI_TESTING_MODE;
// The in-memory adapter is active only in Vite's development preview.
// No fake access token is created or transmitted to the CEOPRO backend.
if (ADMIN_PREVIEW) setPreviewRole("owner");
export { PLATFORM_ADMIN_ME_QUERY_KEY, getPlatformAdminMeQueryKey } from "./platformAdminQueryKeys.js";

const base = "/platform-admin";
const unwrap = (request) => request.then((response) => response.data);

export const platformAdminApi = Object.freeze({
  me: () => ADMIN_PREVIEW ? previewAdapter.me() : unwrap(httpClient.get(`${base}/me`)),

  list: (domain, params, signal) =>
    ADMIN_PREVIEW ? previewAdapter.list(domain, params) :
    unwrap(httpClient.get(`${base}/${domain}`, { params, signal })),

  detail: (domain, id, signal) =>
    ADMIN_PREVIEW ? previewAdapter.detail(domain, id) :
    unwrap(
      httpClient.get(`${base}/${domain}/${encodeURIComponent(id)}`, { signal })
    ),

  mutate: (domain, id, action, payload) =>
    ADMIN_PREVIEW ? previewAdapter.mutate(domain, id, action, payload) : unwrap(
      httpClient.post(
        `${base}/${domain}/${encodeURIComponent(id || "new")}/${action}`,
        payload
      )
    ),

  account: (action, payload) =>
    ADMIN_PREVIEW ? previewAdapter.account(action, payload) : unwrap(
      action === "sessions"
        ? httpClient.get(`${base}/me/sessions`)
        : httpClient.post(`${base}/me/${action}`, payload)
    ),

  notifications: Object.freeze({
    list: (params = {}, signal) =>
      ADMIN_PREVIEW ? Promise.resolve({ data: { items: [], nextCursor: null }, preview: true }) : unwrap(
        httpClient.get(`${base}/notifications`, {
          params,
          signal
        })
      ),

    unreadCount: (signal) =>
      ADMIN_PREVIEW ? Promise.resolve({ data: { unreadCount: 0 }, preview: true }) : unwrap(
        httpClient.get(`${base}/notifications/unread-count`, {
          signal
        })
      ),

    markRead: (id) =>
      ADMIN_PREVIEW ? Promise.resolve({ preview: true }) : unwrap(
        httpClient.post(`${base}/notifications/${encodeURIComponent(id)}/read`)
      ),

    archive: (id) =>
      ADMIN_PREVIEW ? Promise.resolve({ preview: true }) : unwrap(
        httpClient.post(
          `${base}/notifications/${encodeURIComponent(id)}/archive`
        )
      ),

    readAll: () => ADMIN_PREVIEW ? Promise.resolve({ preview: true }) : unwrap(httpClient.post(`${base}/notifications/read-all`))
  }),

  setPreviewRole: async (value) => {
    if (ADMIN_PREVIEW) setPreviewRole(value);
  }
});
