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
    console.log(response?.data?.data);

    // Returns the { connectedSources, recentImports, availableSourceTypes } structure
    // expected by ConnectDataPage[cite: 10]
    return response?.data?.data;
  },

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

  configureWebsite: async (payload) => {
    if (!payload?.url || typeof payload.url !== "string") {
      throw new Error("Website URL is required.");
    }

    const url = payload.url.trim();

    const response = await httpClient.post("/data-connection/sources", {
      name: payload.name?.trim() || new URL(url).hostname,

      sourceType: "website",

      url,

      syncFrequencyMinutes: Number(payload.syncFrequencyMinutes) || 1440
    });

    return response?.data?.data;
  },
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
