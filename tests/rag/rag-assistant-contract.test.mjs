import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
const app = read("src/app.ts");
const route = read("src/modules/rag/route/rag.route.ts");
const service = read("src/modules/rag/service/rag.service.ts");
const repo = read("src/modules/rag/repo/rag.repo.ts");
const client = read("src/modules/rag/client/rag.client.ts");
const types = read("src/modules/rag/types/rag.types.ts");
const usage = read("src/modules/features/repo/usage.repo.ts");
const catalog = read("src/modules/features/catalog.ts");
const plans = read("src/config/production-plans.ts");
const api = read("../frontend/src/features/knowledge-base/api/knowledgeBaseApi.js");
const docRow = read("../frontend/src/features/knowledge-base/components/KnowledgeBaseDocumentRow.jsx");
const citations = read("../frontend/src/features/knowledge-base/components/SourceCitationList.jsx");
const sessions = read("../frontend/src/features/knowledge-base/hooks/useRagChatSessions.js");
const aiMain = read("../ai/src/ai/main.py");
const aiPipeline = read("../ai/src/ai/rag/pipeline.py");
const aiData = read("../ai/src/ai/rag/data_access.py");
const corpus = JSON.parse(read("tests/rag/fixtures/evaluation-cases.json"));

test("active web query is Node + hosted Gradio rag_answer, not AI FastAPI indexed RAG", () => {
  assert.match(app, /app\.use\("\/features\/rag",\s*ragRouter\)/);
  assert.match(route, /router\.post\([\s\S]*?"\/query"[\s\S]*?requireEntitlement\("rag_assistant"\)/);
  assert.match(client, /service:\s*"models"[\s\S]*?apiName:\s*"rag_answer"/);
  assert.doesNotMatch(client, /\/rag\/query/);
  assert.match(aiMain, /@app\.post\("\/rag\/query"\)/);
});

test("Node query constructs Gradio documents, question, top_k and optional history with bounded timeout", () => {
  assert.match(client, /return \[input\.documents, input\.queryText, input\.topK, input\.history\]/);
  assert.match(client, /timeoutMs:\s*120_000/);
  assert.match(client, /documents:[\s\S]*?\.max\(10\)/);
  assert.match(client, /ragQueryResponseSchema\.safeParse/);
});

test("document extraction, retained storage, and RAG token usage are distinct meters", () => {
  assert.match(route, /\/documents[\s\S]*?requireEntitlement\("document_extraction"\)/);
  assert.match(route, /\/query[\s\S]*?requireEntitlement\("rag_assistant"\)/);
  assert.match(service, /featureCode:\s*"document_storage_mb"/);
  assert.match(service, /incrementUsage\(input\.tenantId, "document_extraction"/);
  assert.match(service, /incrementUsage\(input\.tenantId, "rag_assistant"/);
  assert.match(catalog, /code: "rag_assistant"[\s\S]*?unit: "tokens"[\s\S]*?aggregationType: AggregationType\.sum[\s\S]*?resetCycle: ResetCycle\.billing_period/);
  assert.match(catalog, /code: "document_extraction"[\s\S]*?unit: "KB"[\s\S]*?resetCycle: ResetCycle\.billing_period/);
  assert.match(catalog, /code: "document_storage_mb"[\s\S]*?aggregationType: AggregationType\.max[\s\S]*?resetCycle: ResetCycle\.lifetime/);
});

test("standard plan token entitlements match the approved billing-period allowances", () => {
  for (const [plan, limit] of [["starter", "100_000"], ["growth", "500_000"], ["enterprise", "2_000_000"]]) {
    const section = plans.match(new RegExp(`code: "${plan}"[\\s\\S]*?features: \\[([\\s\\S]*?)\\]`))?.[1] ?? "";
    assert.match(section, new RegExp(`limitFeature\\("rag_assistant", ${limit}\\)`));
  }
  assert.match(usage, /currentPeriodStart/);
  assert.match(usage, /currentPeriodEnd/);
  assert.match(usage, /subscription_id_feature_id_period_start/);
});

test("subscription plan feature lookup supplies custom limits and backend authorization", () => {
  assert.match(usage, /planFeatures:[\s\S]*?where:\s*\{\s*feature:\s*\{\s*code:\s*featureCode/);
  assert.match(usage, /status:\s*\{\s*in:\s*accessStatuses\s*\}/);
  assert.match(route, /requireEntitlement\("rag_assistant"\)/);
});

test("RAG supported extension list and upload byte boundary are explicit", () => {
  for (const ext of [".txt", ".md", ".pdf", ".docx", ".xlsx"]) assert.ok(types.includes(`"${ext}"`));
  assert.match(types, /MAX_RAG_DOCUMENT_SIZE_BYTES\s*=\s*2\s*\*\s*1024\s*\*\s*1024/);
  assert.match(route, /fileSize:\s*MAX_RAG_DOCUMENT_SIZE_BYTES/);
  assert.match(service, /input\.file\.size > MAX_RAG_DOCUMENT_SIZE_BYTES/);
});

test("original upload bytes persist in tenant-scoped PostgreSQL BYTEA transactions", () => {
  assert.match(repo, /set_config\('app\.current_tenant_id'/);
  assert.match(repo, /set_config\('app\.current_user_id'/);
  assert.match(repo, /tx\.rag_documents_metadata\.create\([\s\S]*?source_file_content:\s*new Uint8Array/);
  assert.match(repo, /where:\s*\{\s*tenant_id:\s*input\.tenantId/);
  assert.match(repo, /\$transaction\(async \(tx\)/);
});

test("citation chunk lookup and persistence are tenant-scoped and transaction-bound", () => {
  const chunk = repo.match(/export async function getRagChunk\([\s\S]*?(?=\n\nexport async function saveUploadedRagDocument)/)?.[0] ?? "";
  const persist = repo.match(/export async function persistRagQuerySources\([\s\S]*$/)?.[0] ?? "";
  assert.match(chunk, /tenant_id:\s*input\.tenantId/);
  assert.match(chunk, /chunk_id:\s*input\.chunkId/);
  assert.match(persist, /setTenantContext\(tx, input\.tenantId, input\.userId\)/);
  assert.match(persist, /pg_advisory_xact_lock/);
});

test("query candidates are tenant-filtered, marked Processed, and ordered newest first", () => {
  const queryDocs = repo.match(/export async function getRagQueryDocuments\([\s\S]*?(?=\n\nexport async function getRagChunk)/)?.[0] ?? "";
  assert.match(queryDocs, /tenant_id:\s*input\.tenantId/);
  assert.match(queryDocs, /processed_status:\s*"Processed"/);
  assert.match(queryDocs, /orderBy:\s*\[\{ uploaded_at:\s*"desc" \}, \{ document_id:\s*"desc" \}\]/);
  assert.match(queryDocs, /take:\s*input\.limit/);
});

test("token parser prefers provider totals then floors valid component sums", () => {
  const parser = service.match(/function extractTotalTokens\([\s\S]*?(?=\n\nasync function assertUploadEntitlements)/)?.[0] ?? "";
  assert.match(parser, /total_tokens \?\? usage\?\.totalTokens \?\? usage\?\.total/);
  assert.match(parser, /Math\.floor\(explicit\)/);
  assert.match(parser, /input_tokens \?\? usage\?\.prompt_tokens/);
  assert.match(parser, /output_tokens \?\? usage\?\.completion_tokens/);
  assert.match(parser, /Math\.floor\(total\)/);
  const charge = ({ total_tokens, input_tokens = 0, output_tokens = 0 } = {}) => {
    const explicit = Number(total_tokens);
    if (Number.isFinite(explicit) && explicit >= 0) return Math.floor(explicit);
    const total = Number(input_tokens) + Number(output_tokens);
    return Number.isFinite(total) && total > 0 ? Math.floor(total) : 0;
  };
  assert.equal(charge({ input_tokens: 1800, output_tokens: 350 }), 2150);
  assert.equal(charge({ total_tokens: 2150, input_tokens: 1800, output_tokens: 350 }), 2150);
  assert.equal(charge({ total_tokens: 2010, input_tokens: 1800, output_tokens: 350 }), 2010);
  assert.equal(charge({ total_tokens: 5.9 }), 5);
  assert.equal(charge({ input_tokens: 0, output_tokens: 0 }), 0);
  assert.equal(charge({ total_tokens: -1, input_tokens: 2, output_tokens: 3 }), 5);
});

test("fictional evaluation corpus covers five answerable questions, abstention, and supported file signatures", () => {
  assert.equal(corpus.questions.filter((x) => x.answerable).length, 5);
  assert.equal(corpus.questions.filter((x) => !x.answerable).length, 1);
  assert.equal(corpus.questions.find((x) => !x.answerable).expected_fact, null);
  for (const name of ["refund-policy.txt", "shipping-policy.txt", "employee-handbook.md", "arabic-policy.txt", "prompt-injection.txt", "refund-policy.pdf", "employee-procedure.docx", "product-catalog.xlsx"]) {
    assert.ok(read(`tests/rag/fixtures/${name}`).length > 0, `${name} fixture missing`);
  }
  const pdf = readFileSync(new URL("./fixtures/refund-policy.pdf", import.meta.url));
  const docx = readFileSync(new URL("./fixtures/employee-procedure.docx", import.meta.url));
  const xlsx = readFileSync(new URL("./fixtures/product-catalog.xlsx", import.meta.url));
  assert.equal(pdf.subarray(0, 5).toString("ascii"), "%PDF-");
  assert.equal(docx.subarray(0, 2).toString("ascii"), "PK");
  assert.equal(xlsx.subarray(0, 2).toString("ascii"), "PK");
  assert.equal(corpus.latest_ten_case.current_source_available, false);
  assert.equal(corpus.latest_ten_case.acceptance_source_available, true);
});

test("AI-team pipeline uses tenant-keyed indexed retrieval, embeddings, hybrid search, and reranking", () => {
  assert.match(aiPipeline, /build_hybrid_index/);
  assert.match(aiPipeline, /run_retrieval/);
  assert.match(aiPipeline, /rerank/);
  assert.match(aiData, /tenant_id/);
  assert.match(aiData, /processed_status/);
  assert.match(aiMain, /rag_query\(/);
});

test("regression: frontend RAG file-size claims must respect the backend 2 MiB boundary", () => {
  assert.doesNotMatch(api, /10\s*\*\s*1024\s*\*\s*1024/,
    "RAG_UPLOAD_LIMIT_MISMATCH: frontend accepts up to 10 MiB while backend caps each file at 2 MiB.");
});

test("regression: uploaded documents must not claim indexed readiness before indexing completes", () => {
  const upload = service.match(/export async function uploadRagDocument\([\s\S]*?(?=\n\nexport async function getRagDocuments)/)?.[0] ?? "";
  assert.doesNotMatch(upload, /processedStatus:\s*"Processed"/,
    "RAG_INDEXING_UNVERIFIED: upload immediately persists Processed without an indexing/searchability result.");
});

test("regression: Knowledge Base status UI must show the API processed_status", () => {
  assert.match(api, /processed_status/,
    "RAG_DOCUMENT_STATUS_INCORRECT: frontend list mapping hardcodes active and discards Pending/Processed/Failed.");
  assert.match(docRow, /document\.status/);
});

test("regression: citations must preserve document ID, chunk ID, real filename, and evidence excerpt", () => {
  const mapper = api.match(/const formattedSources = Array\.isArray\(payload\?\.sources\)[\s\S]*?\n\s*: \[\];/)?.[0] ?? "";
  assert.match(mapper, /document_id/,
    "RAG_CITATION_PRESENTATION_ERROR: source mapper drops document_id and substitutes chunk_id as documentId.");
  assert.match(mapper, /chunk_id/);
  assert.match(mapper, /documentName|source\.document/);
  assert.match(mapper, /excerpt|source\.text/);
  assert.doesNotMatch(mapper, /Source Document \$\{source\.source_index\}/);
  assert.match(citations, /source\.documentName|source\.name/);
  assert.match(citations, /source\.excerpt/);
});

test("regression: unknown model-generated citations must be rejected instead of returned as evidence", () => {
  const mapping = service.match(/const sources = data\.sources\.map\([\s\S]*?\n\s*\}\);/)?.[0] ?? "";
  assert.match(mapping, /filter\(/,
    "RAG_CITATION_INVALID: unmapped AI citations are returned with null document_id/chunk_id instead of being rejected.");
  assert.match(mapping, /documentId &&.*chunkId|document_id.*chunk_id/);
});

test("regression: token allowance must be reserved before upstream generation to avoid overspend races", () => {
  const query = service.match(/export async function queryRag\([\s\S]*?(?=\n\nexport async function getRagChunkDetail)/)?.[0] ?? "";
  const check = query.indexOf('getRemainingUsage(input.tenantId, "rag_assistant")');
  const request = query.indexOf("await queryRagAi(");
  const charge = query.indexOf('incrementUsage(input.tenantId, "rag_assistant"');
  assert.ok(check >= 0 && request > check && charge > request);
  assert.match(query.slice(check, request), /reserve|lock|transaction|advisory/i,
    "RAG_TOKEN_QUOTA_RACE_CONDITION: quota is read before generation and actual usage is charged after; concurrent answers can overspend.");
});

test("regression: successful answers without provider usage metadata must not be silently unmetered", () => {
  const query = service.match(/export async function queryRag\([\s\S]*?(?=\n\nexport async function getRagChunkDetail)/)?.[0] ?? "";
  assert.doesNotMatch(query, /if \(totalTokens > 0\)/,
    "RAG_TOKEN_METADATA_MISSING: the answer succeeds with zero charge when provider usage is absent or malformed.");
});

test("regression: chat UI must submit supported history or explicitly persist sessions", () => {
  assert.match(api, /history_json/,
    "RAG_CHAT_HISTORY_ERROR: backend accepts history_json but frontend sends a single question with no history.");
  assert.doesNotMatch(api, /sessions:\s*\[\],\s*available:\s*false/,
    "RAG_SESSION_PERSISTENCE_UNAVAILABLE: listSessions is a hard-coded unavailable stub.");
  assert.match(sessions, /knowledgeBaseApi\.listSessions/);
});

test("regression: RAG queries must include the entire eligible corpus or expose document exclusion", () => {
  assert.doesNotMatch(service, /MAX_QUERY_DOCUMENTS\s*=\s*10/,
    "RAG_DOCUMENT_SELECTION_LIMITATION: the query sends at most the 10 newest documents, silently excluding older evidence.");
  assert.equal(corpus.latest_ten_case.document_count, 11);
  assert.equal(corpus.latest_ten_case.expected_source_available, true);
});

test("regression: upload validation must check file signatures and reject corrupt supported extensions", () => {
  const upload = service.match(/export async function uploadRagDocument\([\s\S]*?(?=\n\nexport async function getRagDocuments)/)?.[0] ?? "";
  assert.match(upload, /magic bytes|file-type|signature|parsePdf|validateContent/,
    "RAG_DOCUMENT_UPLOAD_FAILURE: validation checks extension and size but not file signature/content integrity.");
});

test("regression: retained RAG files need a tenant-authorized deletion and reindexing lifecycle", () => {
  assert.match(route, /router\.delete\(["']\/documents/,
    "RAG_DOCUMENT_DELETION_INCONSISTENCY: no document delete or reindex endpoint exists.");
});

test("regression: upload persistence and extraction usage charging need one failure-safe transaction", () => {
  const upload = service.match(/export async function uploadRagDocument\([\s\S]*?(?=\n\nexport async function getRagDocuments)/)?.[0] ?? "";
  assert.match(upload, /\$transaction|reservation|rollback/,
    "RAG_DOCUMENT_UPLOAD_FAILURE: the document row is committed before extraction usage is incremented; a failed charge leaves retained data unmetered.");
});

test("regression: answer generation, citation persistence, and token charging need reconciled failure policy", () => {
  const query = service.match(/export async function queryRag\([\s\S]*?(?=\n\nexport async function getRagChunkDetail)/)?.[0] ?? "";
  assert.match(query, /try[\s\S]*?finally|reservation|idempotency|charge.*before/i,
    "RAG_TOKEN_USAGE_MISMATCH: provider success followed by citation-persistence failure exits before usage is charged; retries can also double-charge.");
});
