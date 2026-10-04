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

test("RAG AI upload points to POST /rag/documents and forwards Authorization", async () => {
  const client = await read("../../src/modules/rag/client/rag.client.ts");
  assert.match(client, /aiUrl\("rag\/documents"\)/);
  assert.match(client, /method:\s*"POST"/);
  assert.match(client, /Authorization:\s*input\.authorization/);
});

test("RAG AI mock mode defaults to true", async () => {
  const client = await read("../../src/modules/rag/client/rag.client.ts");
  assert.match(client, /process\.env\.RAG_AI_USE_MOCKS\s*\?\?\s*"true"/);
});

test("RAG upload accepts only the documented extensions", async () => {
  const types = await read("../../src/modules/rag/types/rag.types.ts");
  for (const extension of [".txt", ".md", ".pdf", ".docx", ".xlsx"]) {
    assert.ok(types.includes(`"${extension}"`), `missing ${extension}`);
  }
  assert.ok(!types.includes('".csv"'));
  assert.ok(!types.includes('".xlsm"'));
});

test("active shared features router no longer owns RAG HTTP routes", async () => {
  const route = await read("../../src/modules/features/route/features.route.ts");
  assert.doesNotMatch(route, /"\/rag\//);
});
