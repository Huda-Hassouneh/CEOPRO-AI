import { expect, test } from "@playwright/test";

const flag = process.env.RAG_ASSISTANT_LIVE_AI === "1";
const apiUrl = process.env.RAG_ASSISTANT_TEST_API_URL;
const databaseUrl = process.env.RAG_ASSISTANT_TEST_DATABASE_URL;
const dbName = (() => { try { return databaseUrl ? new URL(databaseUrl).pathname.replace(/^\//, "").toLowerCase() : ""; } catch { return ""; } })();
const safeDb = process.env.NODE_ENV !== "production" && /(^|[_-])(test|testing|qa|e2e)([_-]|$)/.test(dbName);
const localApi = (() => { try { return ["localhost", "127.0.0.1", "::1"].includes(new URL(apiUrl || "").hostname); } catch { return false; } })();
const enabled = flag && safeDb && localApi && Boolean(
  process.env.RAG_ASSISTANT_API_DATABASE_IDENTITY_VERIFIED === "1" &&
  process.env.RAG_ASSISTANT_TEST_FIXTURES === "1" &&
  process.env.RAG_ASSISTANT_TEST_BEARER_TOKEN &&
  process.env.RAG_ASSISTANT_TEST_TENANT_ID
);

test("RAG Assistant live Gradio > generated answer cites a persisted evaluation passage", async ({ request }, info) => {
  info.annotations.push({ type: "mode", description: "live-hosted-gradio-opt-in" });
  info.annotations.push({ type: "failure-category", description: "RAG_RETRIEVAL_FAILURE" });
  info.annotations.push({ type: "tenant", description: process.env.RAG_ASSISTANT_TEST_TENANT_ID || "not configured" });
  info.annotations.push({ type: "plan", description: process.env.RAG_ASSISTANT_TEST_PLAN || "not configured" });
  info.annotations.push({ type: "eligible-documents", description: "preloaded fictional refund-policy fixture; no upload is performed" });
  info.annotations.push({ type: "question", description: "How many days do customers have to return damaged products?" });
  test.skip(!enabled, "BLOCKED: opt-in requires RAG_ASSISTANT_LIVE_AI=1, local API, verified disposable DB identity, preloaded test fixtures, and a dedicated tenant token. One API query may consume test-plan tokens.");

  const base = apiUrl!.replace(/\/$/, "");
  const query = await request.post(`${base}/features/rag/query`, {
    params: { query_text: "How many days do customers have to return damaged products?", top_k: 3 },
    headers: { Authorization: `Bearer ${process.env.RAG_ASSISTANT_TEST_BEARER_TOKEN}` }
  });
  expect(query.status(), "live Node/Gradio query status").toBe(200);
  const envelope = await query.json();
  const payload = envelope?.data ?? envelope;
  expect(payload.answer).toMatch(/14\s*days/i);
  expect(payload.sources?.length).toBeGreaterThan(0);
  const source = payload.sources.find((item: any) => item.document_id && item.chunk_id);
  expect(source, "citation must resolve to persisted CEOPRO document and chunk IDs").toBeTruthy();
  expect(source.document).toMatch(/refund.policy/i);
  const detail = await request.get(`${base}/features/rag/chunks/${encodeURIComponent(source.chunk_id)}`, {
    headers: { Authorization: `Bearer ${process.env.RAG_ASSISTANT_TEST_BEARER_TOKEN}` }
  });
  expect(detail.status(), "tenant-scoped citation detail status").toBe(200);
  const detailEnvelope = await detail.json();
  const chunk = detailEnvelope?.data ?? detailEnvelope;
  expect(chunk.file_name).toBe(source.document);
  expect(chunk.text_content).toMatch(/14\s*days/i);
});
