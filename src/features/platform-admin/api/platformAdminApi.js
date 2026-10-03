import httpClient from "../../../shared/lib/httpClient.js";

export const ADMIN_PREVIEW = false;

const base = "/platform-admin";
const unwrap = (request) => request.then((response) => response.data);

export const platformAdminApi = Object.freeze({
  me: () => unwrap(httpClient.get(`${base}/me`)),

  list: (domain, params, signal) =>
    unwrap(httpClient.get(`${base}/${domain}`, { params, signal })),

  detail: (domain, id, signal) =>
    unwrap(
      httpClient.get(`${base}/${domain}/${encodeURIComponent(id)}`, { signal })
    ),

  mutate: (domain, id, action, payload) =>
    unwrap(
      httpClient.post(
        `${base}/${domain}/${encodeURIComponent(id || "new")}/${action}`,
        payload
      )
    ),

  account: (action, payload) =>
    unwrap(
      action === "sessions"
        ? httpClient.get(`${base}/me/sessions`)
        : httpClient.post(`${base}/me/${action}`, payload)
    ),

  notifications: Object.freeze({
    list: (params = {}, signal) =>
      unwrap(
        httpClient.get(`${base}/notifications`, {
          params,
          signal
        })
      ),

    unreadCount: (signal) =>
      unwrap(
        httpClient.get(`${base}/notifications/unread-count`, {
          signal
        })
      ),

    markRead: (id) =>
      unwrap(
        httpClient.post(`${base}/notifications/${encodeURIComponent(id)}/read`)
      ),

    archive: (id) =>
      unwrap(
        httpClient.post(
          `${base}/notifications/${encodeURIComponent(id)}/archive`
        )
      ),

    readAll: () => unwrap(httpClient.post(`${base}/notifications/read-all`))
  }),

  setPreviewRole: async () => {}
});
