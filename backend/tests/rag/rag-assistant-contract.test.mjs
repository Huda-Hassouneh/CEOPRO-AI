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
const aiRagRouter=read("../ai/src/ai/routers/rag.py");
const chatRepo=read("src/modules/rag/repo/rag-chat.repo.ts");
const answerValidation=read("src/modules/rag/service/rag-answer.validation.ts");
const sourceMapper=read("../frontend/src/features/knowledge-base/utils/ragChatContract.js");
const uploadValidation=read("src/modules/rag/service/rag-upload.validation.ts");
const aiPipeline = read("../ai/src/ai/rag/pipeline.py");
const aiData = read("../ai/src/ai/rag/data_access.py");
const corpus = JSON.parse(read("tests/rag/fixtures/evaluation-cases.json"));

test("active web query is Node + hosted Gradio rag_answer, not AI FastAPI indexed RAG", () => {
  assert.match(app, /app\.use\("\/features\/rag",\s*ragRouter\)/);
  assert.match(route, /router\.post\([\s\S]*?"\/query"[\s\S]*?requireFeatureAccess\("rag_assistant"\)/);
  assert.match(client, /service:\s*"models"[\s\S]*?apiName:\s*"rag_answer"/);
  assert.doesNotMatch(client, /\/rag\/query/);
  assert.match(aiRagRouter, /@router\.post\("\/query"\)/);
});

test("Node query constructs Gradio documents, question, top_k and optional history with bounded timeout", () => {
  assert.match(client, /return \[input\.documents, input\.queryText, input\.topK, input\.history\]/);
  assert.match(client, /timeoutMs:\s*120_000/);
  assert.match(client, /documents:[\s\S]*?\.max\(10\)/);
  assert.match(client, /ragQueryResponseSchema\.safeParse/);
});

test("document extraction, retained storage, and RAG token usage are distinct meters", () => {
  assert.match(route, /\/documents[\s\S]*?requireEntitlement\("document_extraction"\)/);
  assert.match(route, /\/query[\s\S]*?requireFeatureAccess\("rag_assistant"\)/);
  assert.match(service, /featureCode:\s*"document_storage_mb"/);
  assert.match(repo, /reserveFeatureUsageInTransaction\([\s\S]*?"document_extraction"/);
  assert.match(service, /extractionUsageKb: kbUsed/);
  assert.doesNotMatch(service, /incrementUsage\(input\.tenantId, "document_extraction"/);
  assert.match(chatRepo, /reserveFeatureUsageInTransaction\(tx,c\.tenantId,'rag_assistant'/);
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
  assert.match(route, /requireFeatureAccess\("rag_assistant"\)/);
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

test("query candidates are tenant-filtered and ranked by relevance before recency", () => {
  const queryDocs = repo.match(/export async function getRagQueryDocuments\([\s\S]*?(?=\n\nexport async function getRagChunk)/)?.[0] ?? "";
  assert.match(queryDocs, /tenant_id:\s*input\.tenantId/);
  assert.match(queryDocs, /processed_status:\s*\{ in: \["Stored", "Processed"\] \}/);
  assert.match(queryDocs, /ORDER BY coalesce\(s\.matched_terms,0\) DESC, coalesce\(s\.relevance,0\) DESC/);
  assert.match(queryDocs, /search_vector @@ q\.terms/);
  assert.match(service, /await ensureRagSearchIndex\(input\)/);
});

test("token parser prefers provider totals then floors valid component sums", () => {
  assert.match(answerValidation, /Number\.isSafeInteger/);
  assert.match(answerValidation, /total!==sum/);
  assert.match(service, /totalTokens===null.*USAGE_METADATA_INVALID/);
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
  assert.equal(corpus.latest_ten_case.current_source_available, true);
  assert.equal(corpus.latest_ten_case.acceptance_source_available, true);
});

test("AI-team pipeline uses tenant-keyed indexed retrieval, embeddings, hybrid search, and reranking", () => {
  assert.match(aiPipeline, /build_hybrid_index/);
  assert.match(aiPipeline, /run_retrieval/);
  assert.match(aiPipeline, /rerank/);
  assert.match(aiData, /tenant_id/);
  assert.match(aiData, /processed_status/);
  assert.match(aiRagRouter, /rag_query\(/);
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
  assert.match(sourceMapper, /documentId:source\.document_id/);
  assert.match(sourceMapper, /chunkId:source\.chunk_id/);
  assert.match(sourceMapper, /documentName:source\.document/);
  assert.match(sourceMapper, /excerpt:source\.text/);
  assert.match(citations, /source\.chunkId/);
  assert.match(citations, /source\.excerpt/);
});

test("regression: unknown model-generated citations must be rejected instead of returned as evidence", () => {
  assert.match(service, /!document.*CITATION_INVALID/);
  assert.match(service, /evidenceIsInSource\(source\.text,document\.text\)/);
  assert.match(chatRepo, /SOURCE_CHANGED/);
});

test("regression: token allowance must be reserved before upstream generation to avoid overspend races", () => {
  const reserve=service.indexOf('await beginChatRequest(');
  const generation=service.indexOf('await queryRagAi(');
  assert.ok(reserve>=0 && generation>reserve);
  assert.match(chatRepo, /pg_advisory_xact_lock/);
  assert.match(chatRepo, /reserveFeatureUsageInTransaction/);
});

test("regression: successful answers without provider usage metadata must not be silently unmetered", () => {
  const query = service.match(/export async function queryRag\([\s\S]*?(?=\n\nexport async function getRagChunkDetail)/)?.[0] ?? "";
  assert.doesNotMatch(query, /if \(totalTokens > 0\)/,
    "RAG_TOKEN_METADATA_MISSING: the answer succeeds with zero charge when provider usage is absent or malformed.");
});

test("regression: chat UI must submit supported history or explicitly persist sessions", () => {
  assert.match(api, /session_id:sessionId/);
  assert.match(api, /features\/rag\/sessions/);
  assert.match(chatRepo, /user_id=\$\{c\.userId\}/);
  assert.match(service, /history:boundedHistory/);
});

test("regression: RAG ranks the eligible corpus before enforcing the provider request limit", () => {
  assert.match(service, /await ensureRagSearchIndex\(input\)/);
  assert.match(repo, /FROM public\.rag_document_search_passages p CROSS JOIN q/);
  assert.match(repo, /ORDER BY coalesce\(s\.matched_terms,0\) DESC, coalesce\(s\.relevance,0\) DESC/);
  assert.equal(corpus.latest_ten_case.document_count, 11);
  assert.equal(corpus.latest_ten_case.acceptance_source_available, true);
});

test("regression: upload validation must check file signatures and reject corrupt supported extensions", () => {
  assert.match(service, /ragUploadProblem\(input\.file\)/);
  assert.match(uploadValidation, /signature/);
  assert.match(service, /searchContent\.state==='unreadable'/);
});

test("regression: retained RAG files need a tenant-authorized deletion and reindexing lifecycle", () => {
  assert.match(route, /router\.delete\(["']\/documents/,
    "RAG_DOCUMENT_DELETION_INCONSISTENCY: no document delete or reindex endpoint exists.");
});

test("regression: upload persistence and extraction usage charging need one failure-safe transaction", () => {
  const upload = service.match(/export async function uploadRagDocument\([\s\S]*?(?=\n\nexport async function getRagDocuments)/)?.[0] ?? "";
  assert.match(upload, /extractionUsageKb: kbUsed/);
  assert.match(repo, /saveUploadedRagDocument\([\s\S]*?prisma\.\$transaction[\s\S]*?reserveFeatureUsageInTransaction[\s\S]*?rag_documents_metadata\.create/,
    "RAG_DOCUMENT_UPLOAD_FAILURE: retained document and extraction usage must commit in one transaction.");
});

test("regression: answer generation, citation persistence, and token charging need reconciled failure policy", () => {
  assert.match(service, /catch\(error\)[\s\S]*failChatRequest/);
  assert.match(chatRepo, /finishChatRequest[\s\S]*prisma\.\$transaction[\s\S]*persistRagQuerySources[\s\S]*status='settled'/);
  assert.match(chatRepo, /lookupChatRequest/);
  assert.match(chatRepo, /expireHolds/);
});
