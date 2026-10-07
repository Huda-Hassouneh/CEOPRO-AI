import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("RAG module is mounted at the existing /features/rag API prefix", async () => {
  const app = await read("../../src/app.ts");
  assert.match(app, /app\.use\("\/features\/rag",\s*ragRouter\)/);
});

test("RAG documents POST route uses auth, entitlement and multipart field file", async () => {
  const route = await read("../../src/modules/rag/route/rag.route.ts");
  assert.match(route, /router\.use\(authenticateUser,\s*requireTenant\)/);
  assert.match(route, /router\.post\([\s\S]*?"\/documents"[\s\S]*?requireEntitlement\("document_extraction"\)[\s\S]*?upload\.single\("file"\)/);
});

test("RAG queries use the shared Gradio rag_answer API", async () => {
  const client = await read("../../src/modules/rag/client/rag.client.ts");
  assert.match(client, /service:\s*"models"/);
  assert.match(client, /apiName:\s*"rag_answer"/);
  assert.match(client, /data:\s*buildRagAnswerData\(input\)/);
});

test("RAG query client validates the current Gradio request and response", async () => {
  const client = await read("../../src/modules/rag/client/rag.client.ts");
  assert.match(client, /ragAnswerInputSchema\.safeParse/);
  assert.match(client, /ragQueryResponseSchema\.safeParse/);
});

test("RAG upload accepts only the documented extensions", async () => {
  const types = await read("../../src/modules/rag/types/rag.types.ts");
  for (const extension of [".txt", ".md", ".pdf", ".docx", ".xlsx"]) {
    assert.ok(types.includes(`"${extension}"`), `missing ${extension}`);
  }
  assert.ok(!types.includes('".csv"'));
  assert.ok(!types.includes('".xlsm"'));
});

test("RAG upload size limit matches the 10 MB API contract", async () => {
  const types = await read("../../src/modules/rag/types/rag.types.ts");
  const service = await read("../../src/modules/rag/service/rag.service.ts");
  assert.match(types, /MAX_RAG_DOCUMENT_SIZE_BYTES\s*=\s*10\s*\*\s*1024\s*\*\s*1024/);
  assert.match(service, /RAG documents must not exceed 10 MB/);
});

test("RAG source persistence executes the advisory lock without decoding void", async () => {
  const repo = await read("../../src/modules/rag/repo/rag.repo.ts");
  const persistence = repo.slice(repo.indexOf("export async function persistRagQuerySources"));
  assert.match(persistence, /tx\.\$executeRaw`[\s\S]*?pg_advisory_xact_lock/);
  assert.doesNotMatch(persistence, /tx\.\$queryRaw`[\s\S]*?pg_advisory_xact_lock/);
});

test("active shared features router no longer owns RAG HTTP routes", async () => {
  const route = await read("../../src/modules/features/route/features.route.ts");
  assert.doesNotMatch(route, /"\/rag\//);
});
