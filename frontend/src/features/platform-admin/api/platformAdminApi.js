import httpClient from "../../../shared/lib/httpClient.js";
import { useAuthStore } from "../../auth/store/authStore.js";

// Original Platform Owner screens, connected only to the unified Python API.
export const ADMIN_PREVIEW = false;
export { PLATFORM_ADMIN_ME_QUERY_KEY, getPlatformAdminMeQueryKey } from "./platformAdminQueryKeys.js";
const root = "/platform";
const unwrap = (promise) => promise.then((response) => response.data);
const enc = encodeURIComponent;
const camel = (value) => Array.isArray(value) ? value.map(camel) : value && typeof value === "object" ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key.replace(/_([a-z])/g, (_, c) => c.toUpperCase()), camel(item)])) : value;
const unavailable = (capability) => Promise.reject(Object.assign(new Error(`${capability} is not supported by the Python platform API.`), { code: "BACKEND_CAPABILITY_UNAVAILABLE" }));
const reason = (payload, text) => ({ ...payload, reason: payload?.reason || text });

export const platformAdminApi = Object.freeze({
  me: async () => {
    const data = camel(await unwrap(httpClient.get(`${root}/me`)));
    const session = useAuthStore.getState();
    const role = String(data.role || "").toLowerCase();
    const permissions = role === "owner" ? { all: true } : {
      "platform.overview.read": true, "companies.read": true, "users.read": true,
      "billing.read": true, "adminTeam.read": true, "auditLogs.read": true,
      "platformSettings.read": true
    };
    return { ...data, id: data.userId || session.user?.id, name: session.user?.fullName || session.user?.name || session.user?.email || "", email: session.user?.email || "", role, roleKey: role, status: "active", permissions };
  },
  list: async (domain, params = {}, signal) => {
    const areas = { overview: "overview", companies: "companies", users: "users", "admin-team": "team", "audit-logs": "audit", settings: "settings" };
    const area = areas[domain];
    if (!area) return unavailable(`Platform ${domain} listing`);
    const response = camel(await unwrap(httpClient.get(`${root}/${area}`, { params: { limit: params.pageSize || params.limit || 50, offset: params.offset || 0, ...(params.search ? { search: params.search } : {}) }, signal })));
    if (domain === "overview") return { ...response, active: response.activeSubscriptions ?? null, trials: response.activeTrials ?? null };
    if (domain === "admin-team") {
      const members = (response.members || []).map((item) => ({ ...item, id: item.userId, name: item.fullName, status: item.status === "suspended" ? "inactive" : item.status }));
      const invitations = (response.invitations || []).map((item) => ({ ...item, id: item.invitationId, name: item.email, role: "admin" }));
      return { ...response, items: [...members, ...invitations] };
    }
    if (domain === "settings") return response;
    return { ...response, items: (response.items || []).map((item) => ({ ...item, id: item.tenantId || item.userId, name: item.businessName || item.fullName || item.email, status: item.platformSuspendedAt || item.platformDisabledAt ? "inactive" : "active", notes: item.platformNotes })) };
  },
  detail: async (domain, id, signal) => {
    const item = camel(await unwrap(httpClient.get(`${root}/${domain}/${enc(id)}`, { signal })));
    if (domain === "companies") return { ...item, id: item.tenantId, name: item.businessName, notes: item.platformNotes, status: item.platformSuspendedAt ? "inactive" : "active" };
    if (domain === "users") return { ...item, id: item.userId, name: item.fullName || item.email, status: item.platformDisabledAt ? "inactive" : "active" };
    return item;
  },
  mutate: async (domain, id, action, payload = {}) => {
    if (domain === "companies" && action === "metadata") return camel(await unwrap(httpClient.patch(`${root}/companies/${enc(id)}/metadata`, reason({ notes: payload.notes || "" }, "Platform owner updated company metadata."))));
    if (domain === "companies" && action === "status") return camel(await unwrap(httpClient.patch(`${root}/companies/${enc(id)}/status`, reason({ active: !["inactive", "suspended"].includes(payload.status) }, "Platform owner changed company access."))));
    if (domain === "users" && action === "status") return camel(await unwrap(httpClient.patch(`${root}/users/${enc(id)}/status`, reason({ active: !["inactive", "suspended"].includes(payload.status) }, "Platform owner changed user access."))));
    if (domain === "admin-team" && action === "invite") return camel(await unwrap(httpClient.post(`${root}/team/invitations`, reason({ email: payload.email }, "Platform owner invited an operator."))));
    if (domain === "admin-team" && ["resend", "cancel"].includes(action)) return camel(await unwrap(httpClient.post(`${root}/team/invitations/${enc(id)}/${action}`, { reason: `Platform owner ${action}ed an invitation.` })));
    if (domain === "admin-team" && ["status", "remove"].includes(action)) return camel(await unwrap(httpClient.patch(`${root}/team/${enc(id)}`, { status: action === "remove" ? "removed" : payload.status === "inactive" ? "suspended" : "active", reason: "Platform owner changed operator access." })));
    if (domain === "settings" && action === "update") return unavailable("Platform name and localization settings; Python currently exposes support email only");
    if (domain === "account") return unavailable(`Owner account ${action}`);
    return unavailable(`Platform ${domain} ${action}`);
  },
  account: (action) => unavailable(`Owner account ${action}`),
  notifications: Object.freeze({
    list: async (params = {}, signal) => camel(await unwrap(httpClient.get("/notifications", { params, signal }))),
    unreadCount: async (signal) => camel(await unwrap(httpClient.get("/notifications/unread-count", { signal }))),
    markRead: (id) => unwrap(httpClient.post(`/notifications/${enc(id)}/read`)),
    archive: (id) => unwrap(httpClient.post(`/notifications/${enc(id)}/archive`)),
    readAll: () => unwrap(httpClient.post("/notifications/read-all"))
  }),
  setPreviewRole: async () => undefined
});
