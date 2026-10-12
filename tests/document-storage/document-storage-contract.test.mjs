import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
const ragRoute = read("src/modules/rag/route/rag.route.ts");
const ragService = read("src/modules/rag/service/rag.service.ts");
const ragTypes = read("src/modules/rag/types/rag.types.ts");
const ragRepo = read("src/modules/rag/repo/rag.repo.ts");
const capacity = read("src/modules/features/service/capacity.service.ts");
const catalog = read("src/modules/features/catalog.ts");
const schema = read("prisma/schema.prisma");
const migration = read("prisma/migrations/20261005110000_add_rag_source_file_content/migration.sql");
const knowledgeApi = read("../frontend/src/features/knowledge-base/api/knowledgeBaseApi.js");
const dropzoneValidation = read("../frontend/src/features/data-ingestion/utils/fileValidation.js");
const usageGrid = read("../frontend/src/features/billing/components/UsageLimitGrid.jsx");
const dataconnectionService = read("src/modules/dataconnection/service/dataconnection.service.ts");
const minioPersistence = read("../ai/src/ai/extraction/minio_persistence.py");
const aiDb = read("../ai/src/ai/db.py");
const summaries = read("../ai/src/ai/rag/structured_summaries.py");

test("RAG document upload is authenticated, tenant-scoped, and gated by document extraction", () => {
  assert.match(ragRoute, /router\.use\(authenticateUser, requireTenant\)/);
  assert.match(ragRoute, /requireEntitlement\("document_extraction"\)/);
  assert.match(ragService, /assertFeatureCapacity\([\s\S]*?document_storage_mb/);
});

test("RAG accepts a 2 MiB source file and records original bytes in PostgreSQL BYTEA", () => {
  assert.match(ragTypes, /MAX_RAG_DOCUMENT_SIZE_BYTES\s*=\s*2\s*\*\s*1024\s*\*\s*1024/);
  assert.match(schema, /source_file_content\s+Bytes\?\s+@db\.ByteA/);
  assert.match(migration, /ADD COLUMN IF NOT EXISTS source_file_content BYTEA/);
  assert.match(ragRepo, /source_file_content:\s*new Uint8Array\(input\.sourceFileContent\)/);
  assert.match(ragRepo, /storage_bucket_path:\s*`ceopro-db:\/\/rag-documents/);
});

test("RAG persistence sets tenant context within a transaction for RLS", () => {
  assert.match(ragRepo, /\$transaction\(async \(tx\)/);
  assert.match(ragRepo, /set_config\('app\.current_tenant_id'/);
  assert.match(ragRepo, /set_config\('app\.current_user_id'/);
});

test("storage capacity is a lifetime max and sums persisted RAG metadata in binary MiB", () => {
  const entry = catalog.match(/code: "document_storage_mb"[\s\S]*?\n  \}/)?.[0] ?? "";
  assert.match(entry, /aggregationType: AggregationType\.max/);
  assert.match(entry, /resetCycle: ResetCycle\.lifetime/);
  assert.match(capacity, /rag_documents_metadata\.aggregate/);
  assert.match(capacity, /Number\(bytes\)\s*\/\s*1024\s*\*\*\s*2/);
});

test("business document ingestion calls the separate Gradio flow; it does not retain uploaded originals", () => {
  assert.doesNotMatch(dataconnectionService, /document_storage_mb/);
  assert.match(dataconnectionService, /reserveBusinessFileImport/);
  assert.match(dataconnectionService, /fileSizeBytes/);
  assert.doesNotMatch(dataconnectionService, /source_file_content|put_object\(/);
});

test("AI extraction MinIO stores derived JSON outputs, not the original upload", () => {
  assert.match(minioPersistence, /EXTRACTION_RESULTS_BUCKET\s*=\s*"ceopro-extraction-results"/);
  assert.match(minioPersistence, /content_type\s*=\s*"application\/json"/);
  assert.match(minioPersistence, /tenant_id.*ingestion_job_id|ingestion_job_id.*tenant_id/);
});

test("regression: frontend upload size, allowed formats, and actual backend limit must agree", () => {
const frontendMax = dropzoneValidation.match(/MAX_UPLOAD_FILE_SIZE\s*=\s*([^;\n]+)/)?.[1] ?? "";
  assert.match(frontendMax, /2\s*\*\s*1024\s*\*\s*1024/,
    "UPLOAD_SIZE_MISMATCH: shared frontend validation does not use the RAG API's 2 MiB max.");
  assert.match(dropzoneValidation, /\.md/,
    "UPLOAD_FORMAT_MISMATCH: backend accepts Markdown but shared frontend validation omits it.");
  assert.doesNotMatch(dropzoneValidation, /\.csv|\.png|\.jpe?g/,
    "UPLOAD_FORMAT_MISMATCH: shared frontend accepts file types rejected by the RAG API.");
  assert.match(knowledgeApi, /10\s*\*\s*1024\s*\*\s*1024/,
    "UPLOAD_SIZE_MISMATCH: knowledge base client separately enforces 10 MiB.");
});

test("regression: RAG list UI must preserve persisted processing status", () => {
  assert.match(knowledgeApi, /processed_status/,
    "STATUS_MAPPING_MISMATCH: frontend maps every RAG document to active instead of using the API processing state.");
});

test("regression: backend upload quota check must reserve capacity atomically", () => {
  const upload = ragService.match(/export async function uploadRagDocument\([\s\S]*?\n\}/)?.[0] ?? "";
  assert.match(upload, /await assertUploadEntitlements\(/);
  assert.match(upload, /await saveUploadedRagDocument\(/);
  assert.match(upload, /await assertUploadEntitlements\([\s\S]*?await saveUploadedRagDocument\(/);
  assert.match(ragRepo, /saveUploadedRagDocument\([\s\S]*?reserveFeatureUsageInTransaction[\s\S]*?rag_documents_metadata\.create/,
    "EXTRACTION_QUOTA_RACE: extraction usage and RAG document storage must commit in one transaction.");
});

test("regression: retained RAG documents need an authenticated delete path to reclaim lifetime capacity", () => {
  assert.match(ragRoute, /router\.delete\(["']\/documents/,
    "NO_STORAGE_RECLAMATION: there is no document delete route to reclaim lifetime storage capacity.");
});

test("regression: document storage UI must label binary MiB units consistently", () => {
  assert.match(usageGrid, /MiB/,
    "UNIT_LABEL_MISMATCH: capacity is calculated in binary MiB while the interface calls each unit MB.");
});

test("regression: generated structured summaries must use tenant-scoped MinIO object keys", () => {
  const key = summaries.match(/def _object_key\(slot: str\)[\s\S]*?\n\n/)?.[0] ?? "";
  assert.match(key, /tenant_id/,
    "MINIO_TENANT_KEY_GAP: structured summary object key is not tenant-scoped; shared slot names can collide.");
});

test("MinIO client configuration requires credentials and exposes no restricted role configuration", () => {
  assert.match(aiDb, /MINIO_ENDPOINT/);
  assert.match(aiDb, /MINIO_ROOT_USER/);
  assert.match(aiDb, /MINIO_ROOT_PASSWORD/);
});
