import httpClient from "../../../shared/lib/httpClient.js";

// You can remove the connectDataMockData import if you no longer need it

const previewDelay = (result) =>
  new Promise((resolve) => globalThis.setTimeout(() => resolve(result), 450));

export const dataConnectionsApi = Object.freeze({
  // 1. Pass companyId and use httpClient.get
  list: async (companyId) => {
    const response = await httpClient.get(`/data-connection`);
    console.log({ data: response?.data?.data });

    // If your httpClient automatically unwraps the JSON, just return response.data
    // (since our backend sends { status: "success", data: { ... } })
    return response?.data?.data;
  },

  // ... [Keep your existing mock methods below until backend is ready] ...

  connectGoogleAnalytics: (payload = {}) =>
    previewDelay({
      ok: false,
      operation: "connectGoogleAnalytics",
      payload,
      preview: true,
      connected: false,
      status: "error",
      errorCode: "oauth_not_configured"
    }),

  configureWebsite: (payload) =>
    previewDelay({
      ok: Boolean(payload?.url),
      operation: "configureWebsite",
      payload,
      preview: true,
      connected: Boolean(payload?.url),
      status: payload?.url ? "connected" : "error"
    }),

  prepareDatabase: (payload) =>
    previewDelay({
      ok: true,
      operation: "prepareDatabase",
      payload,
      preview: true,
      connected: false,
      status: "not-connected"
    }),

  sync: (sourceId) =>
    previewDelay({ ok: false, sourceId, available: false, operation: "sync" }),

  reconnect: (sourceId) =>
    previewDelay({
      ok: false,
      sourceId,
      available: false,
      operation: "reconnect"
    })
});
