import { expect, test } from "@playwright/test";

const enabled = process.env.RAG_ASSISTANT_AI_TEAM === "1";
const baseUrl = process.env.RAG_ASSISTANT_AI_TEAM_BASE_URL;
const dbUrl = process.env.RAG_ASSISTANT_TEST_DATABASE_URL;
const dbName = (() => { try { return dbUrl ? new URL(dbUrl).pathname.replace(/^\//, "").toLowerCase() : ""; } catch { return ""; } })();
const safeDb = process.env.NODE_ENV !== "production" && /(^|[_-])(test|testing|qa|e2e)([_-]|$)/.test(dbName);
const localService = (() => { try { return ["localhost", "127.0.0.1", "::1"].includes(new URL(baseUrl || "").hostname); } catch { return false; } })();
const configured = enabled && safeDb && localService &&
  process.env.RAG_ASSISTANT_API_DATABASE_IDENTITY_VERIFIED === "1" &&
  process.env.RAG_ASSISTANT_AI_TEAM_FIXTURES === "1" &&
  Boolean(process.env.RAG_ASSISTANT_AI_TEAM_BEARER_TOKEN);

test("AI-team RAG opt-in > independently query its indexed FastAPI pathway", async ({ request }, info) => {
  info.annotations.push({ type: "mode", description: "ai-team-indexed-rag-opt-in-separate-from-node-gradio" });
  info.annotations.push({ type: "failure-category", description: "RAG_AI_CONTRACT_ERROR" });
  info.annotations.push({ type: "tenant", description: process.env.RAG_ASSISTANT_TEST_TENANT_ID || "not configured" });
  info.annotations.push({ type: "plan", description: "AI-team endpoint does not use Node subscription metering in this call" });
  info.annotations.push({ type: "question", description: "How many days do customers have to return damaged products?" });
  test.skip(!configured, "BLOCKED: opt-in requires a local AI API, verified disposable DB identity, separately indexed fixtures, and RAG_ASSISTANT_AI_TEAM=1. This checks the AI-team FastAPI path, not the active Node/Gradio web path.");

  const url = `${baseUrl!.replace(/\/$/, "")}/rag/query`;
  const response = await request.post(url, {
    params: { query_text: "How many days do customers have to return damaged products?", top_k: 5 },
    headers: { Authorization: `Bearer ${process.env.RAG_ASSISTANT_AI_TEAM_BEARER_TOKEN}` }
  });
  expect(response.status()).toBe(200);
  const payload = await response.json();
  expect(payload.answer).toMatch(/14\s*days/i);
  expect(payload.sources?.length).toBeGreaterThan(0);
  expect(payload.sources.some((source: any) => source.chunk_id)).toBeTruthy();
});
