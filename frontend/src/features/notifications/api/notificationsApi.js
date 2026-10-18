import httpClient from "../../../shared/lib/httpClient.js";

const base = "/notifications";
const unwrap = (request) => request.then((response) => response.data);

export const notificationsApi = Object.freeze({
  list: (params = {}, signal) =>
    unwrap(
      httpClient.get(base, {
        params,
        signal
      })
    ),

  unreadCount: (signal) =>
    unwrap(
      httpClient.get(`${base}/unread-count`, {
        signal
      })
    ),

  markRead: (id) =>
    unwrap(httpClient.post(`${base}/${encodeURIComponent(id)}/read`)),

  archive: (id) =>
    unwrap(httpClient.post(`${base}/${encodeURIComponent(id)}/archive`)),

  readAll: () => unwrap(httpClient.post(`${base}/read-all`))
});
