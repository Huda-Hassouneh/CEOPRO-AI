import { test, type TestInfo } from "@playwright/test";

const databaseUrl = process.env.DOCUMENT_EXTRACTION_TEST_DATABASE_URL;
const apiUrl = process.env.DOCUMENT_EXTRACTION_TEST_API_URL;
const liveAi = process.env.DOCUMENT_EXTRACTION_LIVE_AI === "1";
function databaseName(url?: string): string {
  try { return url ? new URL(url).pathname.replace(/^\//, "").toLowerCase() : ""; }
  catch { return ""; }
}
const safeDb = Boolean(databaseUrl && process.env.NODE_ENV !== "production" && /(^|[_-])(test|testing|qa|e2e)([_-]|$)/.test(databaseName(databaseUrl)));
function blocked(info: TestInfo, category: string, reason: string, tables: string, next: string) {
  info.annotations.push({ type: "mode", description: "document-extraction-deterministic-e2e" });
  info.annotations.push({ type: "failure-category", description: category });
  info.annotations.push({ type: "tenant", description: "not configured" });
  info.annotations.push({ type: "plan", description: "not configured" });
  info.annotations.push({ type: "file-format", description: "scenario dependent" });
  info.annotations.push({ type: "charged-kb", description: "not measured" });
  info.annotations.push({ type: "database-tables", description: tables });
  info.annotations.push({ type: "actual", description: reason });
  info.annotations.push({ type: "recommended-investigation", description: next });
  const prerequisites = [
    safeDb ? null : "an explicitly disposable database whose name contains test/testing/qa/e2e",
    apiUrl ? null : "a real API URL",
    process.env.DOCUMENT_EXTRACTION_TEST_FIXTURES ? null : "isolated tenant fixtures and owned-record cleanup"
  ].filter(Boolean).join(", ");
  test.skip(true, `BLOCKED: these E2E cases are diagnostic registrations only; the fixture-specific API/database assertions are not implemented or configured. Required setup: ${prerequisites || "review and implement fixture-specific assertions"}. ${reason}`);
}

const scenarios: Array<[string, string, string, string, string]> = [
  ["real CSV upload reaches source, job, staging, and worker persistence", "INGESTION_PROMOTION_FAILURE", "data_sources, ingestion_jobs, import_staging_rows, products, transactions", "No verified disposable DB, authenticated tenant, running API/worker, or fixture-cleanup contract is configured.", "Capture upload response and independently compare tenant-scoped source, staging, products, and transactions."],
  ["real XLSX and XLSM uploads preserve canonical sales rows", "FILE_FORMAT_UNSUPPORTED", "ingestion_jobs, import_staging_rows, transactions", "No safe API/DB/worker fixture is configured; local preflight covers CSV/XLSX and the backend allow-list includes XLSM.", "Run each generated fixture through the real route and verify committed rows."],
  ["PDF uploads validate AI-returned headers and extracted rows", "AI_EXTRACTION_UNAVAILABLE", "ingestion_jobs, import_staging_rows", "Live extraction requires approved Gradio access and a disposable tenant/database.", "Use the separate opt-in live AI script and retain job/staging/database evidence."],
  ["downloaded CSV and XLSX templates upload unchanged through the real page", "TEMPLATE_HEADER_MISMATCH", "N/A; upload must not create jobs on rejection", "Frontend template controls currently point at preview assets; no connected browser/API fixture is configured.", "Serve real downloadable template files, capture the browser download, then upload and query job status."],
  ["concurrent uploads cannot exceed extraction quota or leave orphaned jobs", "EXTRACTION_QUOTA_RACE_CONDITION", "subscription_usage, data_sources, ingestion_jobs, import_staging_rows", "No atomic quota reservation and no coordinated DB-backed concurrency fixture are configured.", "Synchronize two 800 KB requests against 1,000 KB remaining; compare usage, jobs and accepted responses."],
  ["failed AI extraction and persistence do not charge or leave partial records", "FAILED_UPLOAD_CHARGING_ERROR", "subscription_usage, data_sources, ingestion_jobs, import_staging_rows", "Requires controlled AI failure injection plus a safe DB transaction fixture.", "Check before/after usage and row counts around provider, validation, and persistence failures."],
  ["job retries resume pending rows without duplicating committed transactions", "DUPLICATE_IMPORT", "ingestion_jobs, import_staging_rows, products, transactions", "No worker DB/role secret or owned isolated tenant fixtures are configured; transaction-level dedupe was not found.", "Crash after a committed batch, restart worker, and compare sale identities and counts."],
  ["RAG uploads remain separate from business sales imports", "TENANT_ISOLATION_FAILURE", "rag_documents_metadata, data_sources, ingestion_jobs, import_staging_rows", "No authenticated RAG/API/DB test fixtures are configured.", "Upload one file to each UI and verify only its flow-owned records and entitlement change."],
  ["tenant A cannot read tenant B jobs or staging payloads", "TENANT_ISOLATION_FAILURE", "ingestion_jobs, import_staging_rows, products, transactions", "No pair of tenant tokens and approved non-BYPASSRLS database role are configured.", "Use RLS-scoped read-only cross-tenant assertions and verify 404/empty API behavior."],
  ["English and Arabic upload copy, loading state, and responsive layout reflect actual contract", "FRONTEND_BACKEND_VALIDATION_MISMATCH", "N/A", "UI strings currently claim 50 MB and unsupported types; browser fixture is not configured.", "Run in English/Arabic at desktop/mobile sizes after copy and template compatibility are corrected."],
  ["live Gradio extraction is opt-in and persists verified imported rows", "AI_EXTRACTION_UNAVAILABLE", "data_sources, ingestion_jobs, import_staging_rows, products, transactions, subscription_usage", "Live AI is disabled; set DOCUMENT_EXTRACTION_LIVE_AI=1 and provide approved service plus test fixtures.", "Record real Gradio execution, CEOPRO job ID, usage delta, staged rows, worker completion, and SQL verification."]
];

for (const [name, category, tables, actual, next] of scenarios) {
  test(`Document Extraction > ${name}`, async ({}, info) => {
    blocked(info, category, actual, tables, next);
    if (name.includes("live Gradio")) test.skip(!liveAi, "BLOCKED: live AI requires explicit DOCUMENT_EXTRACTION_LIVE_AI=1 opt-in.");
  });
}
