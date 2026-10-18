import { translateCurrent } from '../../../shared/lib/i18n.js';
import httpClient from "../../../shared/lib/httpClient.js";

export const dataConnectionsApi = Object.freeze({
  storePrivacyReports: async (id) => (await httpClient.get(`/data-connection/store/${encodeURIComponent(id)}/privacy-reports`)).data.data,
  finishShopify: async (ticket) => (await httpClient.post('/data-connection/store/shopify/complete',{ticket})).data.data,
  authorizeShopify: async (payload) => (await httpClient.post('/data-connection/store/shopify/authorize',payload)).data.data,
  detectStore: async (url) => (await httpClient.post('/data-connection/store/detect',{url})).data.data,
  connectStore: async (payload) => (await httpClient.post('/data-connection/store/connect',payload)).data.data,
  syncStore: async (sourceId) => (await httpClient.post(`/data-connection/store/${encodeURIComponent(sourceId)}/sync`,{})).data.data,
  disconnectStore: async (sourceId) => (await httpClient.delete(`/data-connection/store/${encodeURIComponent(sourceId)}`)).data.data,
  list: async ({ companyId }) => {
    // Tenant scope comes from the authenticated session, never a query value.
    void companyId;
    const response = await httpClient.get("/data-connection");
    return response?.data?.data;
  },

  configureWebsite: async (payload) => {
    if (!payload?.url || typeof payload.url !== "string") {
      throw new Error(translateCurrent("interfaceCopy.websiteUrlRequired"));
    }

    const url = payload.url.trim();
    const response = await httpClient.post("/data-connection/sources", {
      name: payload.name?.trim() || new URL(url).hostname,
      sourceType: "website",
      sourceUrl: url,
      syncFrequencyMinutes: Number(payload.syncFrequencyMinutes) || 1440
    });

    return response?.data?.data;
  },

  setActive: async (sourceId, isActive) => {
    const response = await httpClient.patch(
      `/data-connection/sources/${encodeURIComponent(sourceId)}`,
      { isActive }
    );
    return response?.data?.data;
  },

  disconnect: async (sourceId) => {
    const response = await httpClient.delete(
      `/data-connection/sources/${encodeURIComponent(sourceId)}/connection`
    );
    return response?.data?.data;
  }
});
