import { test, type TestInfo } from "@playwright/test";

function blocked(info: TestInfo, category: string, tables: string, actual: string, next: string) {
  for (const [type, description] of [
    ["mode", "document-storage-diagnostic-e2e"],
    ["failure-category", category],
    ["tenant", "not configured"],
    ["plan", "not configured"],
    ["database-tables", tables],
    ["actual", actual],
    ["recommended-investigation", next]
  ]) info.annotations.push({ type, description });
  const required = [
    process.env.DOCUMENT_STORAGE_TEST_DATABASE_URL ? null : "a disposable migrated test database",
    process.env.DOCUMENT_STORAGE_TEST_API_URL ? null : "a real API URL and authenticated test tenant",
    process.env.DOCUMENT_STORAGE_TEST_FIXTURES ? null : "isolated fixtures with owned-record cleanup",
    process.env.DOCUMENT_STORAGE_MINIO_ENDPOINT ? null : "a disposable MinIO endpoint and test bucket"
  ].filter(Boolean).join(", ");
  test.skip(true, `BLOCKED: real storage E2E assertions require ${required || "implemented fixture-specific assertions"}. ${actual}`);
}

const cases: Array<[string, string, string, string, string]> = [
  ["uploads a RAG file and independently verifies BYTEA bytes and tenant metadata", "PERSISTENCE_FAILURE", "rag_documents_metadata", "No safe DB/API/tenant fixture is configured.", "Compare uploaded bytes, file_size_bytes, tenant_id, and source_file_content using an RLS-scoped read."],
  ["concurrent uploads cannot exceed a tenant's storage quota", "STORAGE_QUOTA_RACE", "rag_documents_metadata", "No atomic reservation or coordinated tenant DB fixture is configured.", "Race two uploads whose combined size exceeds remaining storage and verify accepted count plus quota state."],
  ["tenant A cannot list, query, or retrieve tenant B documents", "TENANT_ISOLATION_FAILURE", "rag_documents_metadata", "No paired tenant tokens or non-BYPASSRLS database role is configured.", "Verify API denial and direct RLS-scoped reads for both tenants."],
  ["delete removes stored bytes and restores available lifetime capacity", "NO_STORAGE_RECLAMATION", "rag_documents_metadata", "No delete route/UI exists; safe cleanup behavior is not implemented.", "Implement authenticated delete, remove the owned object/row transactionally, and verify quota reclamation."],
  ["RAG upload enforces byte limit and frontend only accepts backend-supported types", "UPLOAD_SIZE_MISMATCH", "N/A", "RAG limit is 2 MiB; shared frontend validation is 50 MiB and accepts extra formats.", "Exercise 2 MiB boundary and every allowed/rejected extension in the browser and API."],
  ["business extraction transient files do not consume retained-storage capacity", "METER_SCOPE_MISMATCH", "data_sources, rag_documents_metadata", "Business extraction checks the storage capacity feature, while capacity totals only RAG document metadata.", "Verify business-upload acceptance at storage quota boundary and compare retained bytes separately."],
  ["derived extraction JSON is tenant-isolated in MinIO and access is least privilege", "MINIO_TENANT_KEY_GAP", "ceopro-extraction-results, ceopro-rag-knowledge", "No disposable MinIO, restricted test identity, or tenant fixtures are configured.", "Verify bucket policies, tenant-scoped keys, cross-tenant denial, overwrite behavior, and cleanup."],
  ["structured summary objects from two tenants never share an object key", "MINIO_TENANT_KEY_GAP", "ceopro-rag-knowledge", "Current summary key builder uses a slot path without tenant ID.", "Generate identical summary slots for two tenants and verify distinct keys and isolated reads."],
  ["billing usage display agrees with capacity bytes and plan limits", "UNIT_LABEL_MISMATCH", "N/A", "Backend computes binary MiB while UI labels the unit MB; no browser fixture is configured.", "Compare 1 MiB and 1 GiB boundaries against the displayed labels and plan allowance." ]
];

for (const [name, category, tables, actual, next] of cases) {
  test(`Document Storage > ${name}`, async ({}, info) => blocked(info, category, tables, actual, next));
}
