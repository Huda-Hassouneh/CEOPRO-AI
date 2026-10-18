/**
 * Development-only UI fixtures. These are illustrative, not tenant data or an
 * implementation of the production API. Never ship an authenticated mock.
 * Each route is explicitly handled; unknown routes fail closed without network.
 */
import { getMockDashboard } from "../../features/dashboard/mocks/dashboardMockData.js";
import { getMockMarketIntelligence } from "../../features/market-intelligence/mocks/marketIntelligenceMockData.js";
import { getMockDemandOverview, getMockDemandDetail } from "../../features/forecasting/mocks/demandPredictionMockData.js";
import { connectDataMockData } from "../../features/data-connections/mocks/connectDataMockData.js";

const localized = (en, ar) => ({ en, ar });
const date = "2026-10-09T12:00:00.000Z";
const competitors = [
  { id: "demo-competitor-1", name: "Northstar Commerce", website: "https://northstar.example", industry: "Analytics", addedAt: date },
  { id: "demo-competitor-2", name: "Meridian Systems", website: "https://meridian.example", industry: "Analytics", addedAt: "2026-10-07T10:00:00Z" },
  { id: "demo-competitor-3", name: "Summit Works", website: "https://summit.example", industry: "Internet", addedAt: "2026-10-06T10:00:00Z" },
  { id: "demo-competitor-4", name: "Harbor Digital", website: "https://harbor.example", industry: "Telecom", addedAt: "2026-10-05T10:00:00Z" },
];

export function getPreviewCompetitors() { return structuredClone(competitors); }
export function getPreviewCompetitorDetail(id) {
  const company = competitors.find(c => c.id === id);
  if (!company) return null;
  return {
    ...company,
    mappedProducts: [
      { id: `${id}-1`, name: localized("Team Workspace", "مساحة عمل الفريق"), ourPrice: 64, competitorPrice: 62, currency: "JOD", lastUpdated: date },
      { id: `${id}-2`, name: localized("Insights Package", "حزمة الرؤى"), ourPrice: 89, competitorPrice: 94, currency: "JOD", lastUpdated: date },
    ],
    activity: [{ id: `${id}-activity`, productName: localized("Team Workspace", "مساحة عمل الفريق"), previousPrice: 66, newPrice: 62, currency: "JOD", date }],
  };
}
const mockDocuments = [
  { document_id: "preview-document-1", file_name: "Demo_Flower_Shop_Sales_2026.xlsx", file_size_bytes: 420145, content_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", uploaded_at: date },
  { document_id: "preview-document-2", file_name: "Demo_Inventory_Policy.pdf", file_size_bytes: 110482, content_type: "application/pdf", uploaded_at: date },
];

/** Return an Axios-shaped response, or throw a clearly identified preview error. */
export async function previewAxiosAdapter(config) {
  const method = (config.method || "get").toLowerCase();
  const path = new URL(config.url || "/", "http://preview.invalid").pathname;
  if (method !== "get" && method !== "head") {
    const error = new Error("UI testing is read-only. Changes, payments and uploads are disabled.");
    error.code = "UI_TESTING_READ_ONLY";
    throw error;
  }
  const days = Number(config.params?.periodDays) || 30;
  let body;
  // Match route contracts rather than returning generic empty payloads.
  if (/^\/companies\/[^/]+\/dashboard$/.test(path)) body = getMockDashboard(days);
  else if (path === "/forecasting/demand") body = getMockDemandOverview({ productId: config.params?.productId || "all", periodDays: days });
  else if (path.startsWith("/forecasting/demand/")) {
    body = getMockDemandDetail(decodeURIComponent(path.slice("/forecasting/demand/".length)));
    if (body) body = { ...body, filters: { periodDays: days } };
  }
  else if (path === "/market-intelligence") body = getMockMarketIntelligence({productId: config.params?.productId || undefined, periodDays: days});
  else if (path === "/competitors") body = getPreviewCompetitors();
  else if (path.startsWith("/competitors/")) body = getPreviewCompetitorDetail(decodeURIComponent(path.slice("/competitors/".length)));
  else if (path === "/leaderboard") body = getPreviewCompetitors().map((row, idx) => ({ ...row, compositeScore: 85 - idx * 7 }));
  else if (path === "/data-connection") body = structuredClone(connectDataMockData);
  else if (path === "/features/rag/documents") body = {
    documents: structuredClone(mockDocuments),
    pagination: { page: Number(config.params?.page) || 1, pageSize: 10, total: mockDocuments.length, totalPages: 1 },
  };
  else if (path.startsWith("/features/rag/chunks/")) body = {
    chunk_id: path.split("/").at(-1), content: "Fictional example excerpt for UI testing. Not an AI answer or company document.", score: 0.93, source_index: 1,
  };
  else if (path === "/notifications") body = { notifications: [], total: 0, unreadCount: 0, preview: true };
  else if (path === "/notifications/unread-count") body = { count: 0, unreadCount: 0, preview: true };
  if (body === undefined) {
    const error = new Error(`No UI testing fixture for GET ${path}. No backend request was made.`);
    error.code = "UI_TESTING_FIXTURE_MISSING";
    throw error;
  }
  return { data: { data: structuredClone(body), preview: true }, status: 200, statusText: "OK", headers: {}, config };
}
