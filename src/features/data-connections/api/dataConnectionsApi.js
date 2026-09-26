import httpClient from "../../../shared/lib/httpClient.js";

const previewDelay = (result) =>
  new Promise((resolve) => globalThis.setTimeout(() => resolve(result), 450));

export const dataConnectionsApi = Object.freeze({
  // 1. Destructure { companyId } to match the useDataConnections hook payload[cite: 11]
  list: async ({ companyId }) => {
    // Pass the companyId as a query parameter if your backend requires it for scoping,
    // otherwise the backend can just extract it from the bearer token.
    const response = await httpClient.get(`/data-connection`, {
      params: { tenantId: companyId }
    });

    // Returns the { connectedSources, recentImports, availableSourceTypes } structure
    // expected by ConnectDataPage[cite: 10]
    return response?.data?.data;
  },

  // --- MOCKED METHODS (Keep until backend endpoints are ready) ---

  connectGoogleAnalytics: async (sourceId) => {
    try {
      console.log({ sourceId });

      const response = await httpClient.post(
        `/data-connection/${sourceId}/sync`
      );
      return { ok: true, available: true, ...response.data.data };
    } catch (error) {
      return { ok: false, available: false, error };
    }
  },

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
