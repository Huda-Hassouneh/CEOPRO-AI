import { test, type TestInfo } from "@playwright/test";

const databaseUrl = process.env.RAG_ASSISTANT_TEST_DATABASE_URL;
const frontendUrl = process.env.RAG_ASSISTANT_TEST_FRONTEND_URL;
const apiUrl = process.env.RAG_ASSISTANT_TEST_API_URL;
const dbName = (() => { try { return databaseUrl ? new URL(databaseUrl).pathname.replace(/^\//, "").toLowerCase() : ""; } catch { return ""; } })();
const safeDb = process.env.NODE_ENV !== "production" && /(^|[_-])(test|testing|qa|e2e)([_-]|$)/.test(dbName);

function blocked(info: TestInfo, category: string, tables: string, reason: string, next: string, extra: Record<string, string> = {}) {
  for (const [type, description] of Object.entries({
    mode: "rag-assistant-deterministic-e2e",
    "failure-category": category,
    tenant: process.env.RAG_ASSISTANT_TEST_TENANT_ID || "not configured",
    user: process.env.RAG_ASSISTANT_TEST_USER_ID || "not configured",
    plan: process.env.RAG_ASSISTANT_TEST_PLAN || "not configured",
    "database-tables": tables,
    actual: reason,
    "recommended-investigation": next,
    ...extra
  })) info.annotations.push({ type, description });
  const missing = [
    safeDb ? null : "a dedicated disposable DB whose name contains test/testing/qa/e2e",
    process.env.RAG_ASSISTANT_API_DATABASE_IDENTITY_VERIFIED === "1" ? null : "verified API database identity",
    frontendUrl ? null : "a real frontend URL",
    apiUrl ? null : "a real backend API URL",
    process.env.RAG_ASSISTANT_TEST_FIXTURES === "1" ? null : "owned tenant/document fixtures and safe cleanup"
  ].filter(Boolean).join(", ");
  test.skip(true, `BLOCKED: fixture-specific browser/API/SQL assertions cannot run without ${missing || "implemented scenario assertions"}. ${reason}`);
}

const cases: Array<[string, string, string, string, string]> = [
  ["upload supported TXT and independently verify tenant BYTEA persistence", "RAG_DOCUMENT_UPLOAD_FAILURE", "rag_documents_metadata", "No disposable DB/API/tenant fixture is configured.", "Compare uploaded bytes, file size, name, tenant, and extraction/storage usage in an RLS-scoped DB read."],
  ["upload Markdown, PDF, DOCX, and XLSX fixtures", "RAG_DOCUMENT_UPLOAD_FAILURE", "rag_documents_metadata", "No real upload browser/API fixture is configured; only source extension validation was checked.", "Exercise every supported format, corrupt files, signatures, empty files, Unicode, Arabic, tables, and duplicate names."],
  ["enforce below, exact, and one-byte-over 2 MiB upload boundaries", "RAG_UPLOAD_LIMIT_MISMATCH", "rag_documents_metadata", "Frontend currently advertises 10 MiB while backend accepts at most 2 MiB.", "Upload sizes 2 MiB-1, 2 MiB, and 2 MiB+1 and compare browser and API behavior."],
  ["stored document is not shown as searchable before successful processing", "RAG_DOCUMENT_STATUS_INCORRECT", "rag_documents_metadata, rag_document_chunks", "Upload immediately records Processed; no Node upload indexing step was found.", "Verify status transitions against actual retrieval readiness in the selected production architecture."],
  ["AI indexing failure and service outage do not show a ready badge", "RAG_INDEXING_UNVERIFIED", "rag_documents_metadata, rag_document_chunks", "Node Gradio upload path has no indexing-state callback to exercise.", "Inject controlled processor failure and verify truthful states and UI labels."],
  ["ask a direct question and verify retrieved evidence independently", "RAG_RETRIEVAL_FAILURE", "rag_documents_metadata, rag_document_chunks", "No test tenant, stored evaluation corpus, or hosted Gradio fixture is configured.", "Record eligible docs, request docs, cited chunks, and source text for each known-answer case."],
  ["answer an unanswerable warranty question without inventing a value", "RAG_HALLUCINATED_ANSWER", "rag_documents_metadata, rag_document_chunks", "No live/simulated provider fixture is configured for this API-level run.", "Use the fictional corpus and assert abstention is supported by empty or irrelevant retrieved evidence."],
  ["surface contradictory refund policies without silently choosing one", "RAG_ANSWER_NOT_GROUNDED", "rag_documents_metadata, rag_document_chunks", "No conflicting-document tenant fixture is configured.", "Record retrieved policy versions, answer, citations, and explicit conflict handling."],
  ["show authentic document name, passage, document ID, and chunk ID in citations", "RAG_CITATION_PRESENTATION_ERROR", "rag_documents_metadata, rag_document_chunks", "Source mapper currently labels sources generically and drops real document identity/excerpt.", "Click each source and compare displayed name/excerpt with the tenant-owned chunk endpoint."],
  ["reject fabricated citation IDs and safely handle missing/deleted chunks", "RAG_CITATION_INVALID", "rag_documents_metadata, rag_document_chunks", "No safe tenant/API citation fixture is configured.", "Try nonexistent, deleted, and other-tenant chunk IDs and verify no evidence is accepted."],
  ["two users share one tenant token allowance and cannot race past it", "RAG_TOKEN_QUOTA_RACE_CONDITION", "subscriptions, plan_features, subscription_usage", "Quota read and actual charge are separate operations; no DB concurrency fixture is configured.", "Start two controlled 1,500-token calls with 2,000 remaining; independently read usage and provider reports."],
  ["five and ten simultaneous questions reconcile reported usage once", "RAG_TOKEN_USAGE_MISMATCH", "subscriptions, subscription_usage", "No controlled provider concurrency adapter and safe DB are configured.", "Capture each request ID/provider total and reconcile persisted feature usage after retries and disconnects."],
  ["verify plan upgrade, downgrade, expiration, suspension, and billing reset", "RAG_BILLING_PERIOD_ERROR", "subscriptions, plans, plan_features, subscription_usage", "No disposable subscription fixtures or billing API test helper is configured.", "Test effective entitlement and currentPeriodStart/End against DB and the public entitlement response."],
  ["deny direct chat API calls without an effective rag_assistant entitlement", "ENTITLEMENT_FAILURE", "subscriptions, plan_features", "No authenticated API tenant fixture is configured.", "Use Starter/Growth/Enterprise/custom, disabled, missing, expired, suspended, and exhausted fixture subscriptions."],
  ["tenant A cannot list, query, or cite tenant B documents and chunks", "RAG_TENANT_ISOLATION_FAILURE", "rag_documents_metadata, rag_document_chunks", "No paired tenant tokens or restricted DB runtime role are configured.", "Try known fixture marker ALPHA-2847/BETA-9162 via APIs and RLS-scoped reads without disabling RLS."],
  ["oldest answer-bearing document remains available when the tenant has eleven files", "RAG_DOCUMENT_SELECTION_LIMITATION", "rag_documents_metadata", "Current Node query selects only the ten newest eligible documents.", "Place the only matching fact in the oldest item and record selection and answer evidence."],
  ["follow-up question uses prior turns and session history behaves as documented", "RAG_CHAT_HISTORY_ERROR", "N/A", "Frontend stores messages transiently but does not send history_json; persistent sessions are unavailable.", "Compare response before/after refresh, navigation, tab, user, tenant, and history length boundaries."],
  ["provider timeout, malformed output, and retry failures report correct errors and charges", "RAG_AI_SERVICE_UNAVAILABLE", "subscription_usage", "No controlled provider failure-injection fixture is configured.", "Inject pre-generation timeout, post-generation disconnect, malformed sources, and retries; compare token deltas."],
  ["prompt injection in an uploaded document remains untrusted evidence", "RAG_PROMPT_INJECTION_FAILURE", "rag_documents_metadata, rag_document_chunks", "No safe hosted model fixture and test tenant are configured.", "Use the fictional injection file; assert no cross-tenant disclosure and safe text rendering."],
  ["document deletion prevents retrieval and follows retention/quota policy", "RAG_DOCUMENT_DELETION_INCONSISTENCY", "rag_documents_metadata, rag_document_chunks", "No deletion or reindex route/UI exists in the checked Node app.", "Define retention, then verify bytes, chunks, citations, quota, and tenant ownership after deletion."],
  ["Arabic/English labels, RTL layout, keyboard navigation, and mobile chat work", "FRONTEND_LOCALIZATION_ERROR", "N/A", "No configured frontend server or browser fixtures are available.", "Run English and Arabic at desktop/mobile sizes and inspect accessibility tree, tab order, and evidence panel."],
  ["query and citation UI displays bounded loading and AI error states", "RAG_FALSE_SUCCESS_UI", "N/A", "No real frontend/API browser fixture is configured.", "Exercise empty library, insufficient evidence, 402 quota, 502 AI error, and chunk-detail 404."],
  ["verify token display agrees with independent persisted usage", "RAG_TOKEN_USAGE_MISMATCH", "subscriptions, subscription_usage", "No live API plus read-only restricted DB fixture is configured.", "Compare provider report, stored usage, entitlement response, and frontend display before/after one call."],
  ["verify source passages and escaped HTML-like answer text in the actual browser", "RAG_CITATION_PRESENTATION_ERROR", "rag_document_chunks", "No browser test tenant or response fixture is configured.", "Check exact citation excerpt and ensure user/model text is rendered as text, not executable HTML."]
];

for (const [name, category, tables, actual, next] of cases) {
  test(`RAG Assistant > ${name}`, async ({}, info) => blocked(info, category, tables, actual, next));
}
