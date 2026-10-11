import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
const service = read("src/modules/dataconnection/service/dataconnection.service.ts");
const repo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
const worker = read("src/modules/dataconnection/repo/ingestion-worker.repo.ts");
const route = read("src/modules/dataconnection/route/dataconnection.route.ts");
const controller = read("src/modules/dataconnection/controller/dataconnection.controller.ts");
const uploadValidation = read("src/modules/dataconnection/types/dataconnection.validation.ts");
const usage = read("src/modules/features/repo/usage.repo.ts");
const capacity = read("src/modules/features/service/capacity.service.ts");
const catalog = read("src/modules/features/catalog.ts");
const plans = read("src/config/production-plans.ts");
const workerMigration = read("prisma/migrations/20261006120000_business_data_ingestion_worker/migration.sql");
const schema = read("prisma/schema.prisma");
const templateConfig = read("../frontend/src/features/data-ingestion/config/dataTemplateOptions.js");
const dropzone = read("../frontend/src/features/data-ingestion/components/FileUploadDropzone.jsx");
const ingestionApi = read("../frontend/src/features/data-ingestion/api/ingestionApi.js");
const en = JSON.parse(readFileSync(new URL("../../../frontend/src/assets/locales/en.json", import.meta.url), "utf8"));
const ar = JSON.parse(readFileSync(new URL("../../../frontend/src/assets/locales/ar.json", import.meta.url), "utf8"));

test("actual upload route enforces authenticated tenant and document_extraction entitlement", () => {
  assert.match(route, /router\.use\(authenticateUser, requireTenant\)/);
  assert.match(route, /requireEntitlement\("document_extraction"\)[\s\S]*?upload\.single\("file"\)/);
  assert.match(controller, /tenantId = req\.tenant_id/);
  assert.match(controller, /userId = req\.user\?\.user_id/);
});

test("preflight size comes from MAX_UPLOAD_BYTES (10 MiB default) and supports CSV/XLSX/XLSM/PDF", () => {
  assert.match(uploadValidation, /process\.env\.MAX_UPLOAD_BYTES/);
  assert.match(uploadValidation, /10 \* 1024 \* 1024/);
  assert.match(uploadValidation, /\.csv[\s\S]*\.xlsx[\s\S]*\.xlsm[\s\S]*\.pdf/);
});

test("document extraction is a KB sum meter reset on the subscription billing period", () => {
  const feature = catalog.match(/code: "document_extraction"[\s\S]*?\n  \}/)?.[0] ?? "";
  assert.match(feature, /unit: "KB"/);
  assert.match(feature, /aggregationType: AggregationType\.sum/);
  assert.match(feature, /resetCycle: ResetCycle\.billing_period/);
  for (const [plan, limit] of [["starter", "51_200"], ["growth", "512_000"], ["enterprise", "2_097_152"]]) {
    const section = plans.match(new RegExp(`code: "${plan}"[\\s\\S]*?features: \\[([\\s\\S]*?)\\]`))?.[1] ?? "";
    assert.match(section, new RegExp(`limitFeature\\("document_extraction", ${limit}\\)`));
  }
});

test("document extraction byte rounding charges one KB minimum and rounds partial KB upward", () => {
  const charge = (bytes) => Math.max(1, Math.ceil(bytes / 1024));
  assert.match(service, /Math\.max\(1, Math\.ceil\(input\.file\.size \/ 1024\)\)/);
  for (const [bytes, expected] of [[1, 1], [1023, 1], [1024, 1], [1025, 2], [1537, 2]]) {
    assert.equal(charge(bytes), expected, `${bytes} bytes`);
  }
});

test("usage is charged only after AI extraction validates and tenant staging persistence succeeds", () => {
  assert.ok(service.indexOf("validateExtractionUpload(input.file)") < service.indexOf("uploadExtractionFile({"));
  assert.ok(service.indexOf("uploadExtractionFile({") < service.indexOf("validateExtractionResultForDataConnection(data)"));
  assert.ok(service.indexOf("validateExtractionResultForDataConnection(data)") < service.indexOf("recordBusinessFileIngestion({"));
  assert.ok(service.indexOf("recordBusinessFileIngestion({") < service.indexOf("incrementUsage(input.tenantId, \"document_extraction\""));
  assert.match(service, /Math\.ceil\(input\.file\.size \/ 1024\)/);
});

test("Gradio is separate from the AI FastAPI extraction-upload endpoint", () => {
  const client = read("src/modules/dataconnection/client/ingestion.client.ts");
  const aiMain = read("../ai/src/ai/main.py");
  assert.match(client, /service: "analytics"[\s\S]*apiName: "extract_file"/);
  assert.match(client, /file\.buffer\.toString\("base64"\)/);
  assert.match(aiMain, /@app\.post\("\/extraction\/upload"\)/);
  assert.doesNotMatch(service, /fetch\([^\n]*\/extraction\/upload/);
});

test("CEOPRO owns source/job/staging IDs and stages rows under its authenticated tenant", () => {
  assert.match(service, /const jobId = randomUUID\(\)/);
  assert.match(repo, /recordBusinessFileIngestion: async/);
  assert.match(repo, /set_config\('app\.current_tenant_id'/);
  assert.match(repo, /source_type: "documents"/);
  assert.match(repo, /is_active: false/);
  assert.match(repo, /job_status: "QUEUED"/);
  assert.match(repo, /import_staging_rows\.createMany/);
});

test("worker uses leased SKIP LOCKED claims, bounded retry, and transaction-bound promotion", () => {
  assert.match(worker, /FOR UPDATE OF j SKIP LOCKED/);
  assert.match(worker, /INGESTION_WORKER_MAX_ATTEMPTS = 5/);
  assert.match(worker, /MAX_RETRY_MS/);
  assert.match(worker, /validation_status: "PENDING"/);
  assert.match(worker, /tx\.transactions\.create/);
  assert.match(worker, /validation_status: "COMMITTED"/);
  assert.match(worker, /job_status: "COMPLETED"/);
});

test("product matching is tenant-scoped and protects existing manually maintained prices", () => {
  const productLookup = worker.match(/async function ensureImportedProduct[\s\S]*?type BatchResult/)?.[0] ?? "";
  assert.match(productLookup, /pg_advisory_xact_lock/);
  assert.match(productLookup, /p\.tenant_id = \$\{tenantId\}::uuid/);
  assert.doesNotMatch(productLookup, /products\.update|current_price:\s*unitPrice[\s\S]*?update/);
});

test("source contract records current transaction dedupe limitation", () => {
  const create = worker.match(/tx\.transactions\.create\([\s\S]*?\n    \}\);/)?.[0] ?? "";
  assert.ok(create);
  assert.doesNotMatch(create, /invoice_id|order_id|idempotency|external_id/i,
    "DUPLICATE_IMPORT: product reuse exists, but no transaction-level identity key is applied in the worker insert.");
});

test("worker RLS policies are tenant-correlated and scoped to its least-privilege role", () => {
  assert.match(workerMigration, /CREATE ROLE ceopro_ingestion_worker/);
  assert.match(workerMigration, /GRANT SELECT, UPDATE ON TABLE ingestion_jobs, import_staging_rows/);
  assert.match(workerMigration, /j\.tenant_id = import_staging_rows\.tenant_id/);
  assert.match(schema, /model transactions \{[\s\S]*?tenant_id/);
});

test("regression: extraction quota check and usage increment must be atomic", () => {
  const check = service.indexOf("getRemainingUsage(");
  const increment = service.indexOf("incrementUsage(input.tenantId, \"document_extraction\"");
  const sharedTransaction = /\$transaction|FOR UPDATE|advisory_xact_lock|SERIALIZABLE/i.test(service.slice(check, increment));
  assert.ok(sharedTransaction,
    "EXTRACTION_QUOTA_RACE_CONDITION: remaining quota is read before extraction and charged later with no reservation/atomic transaction.");
});

test("regression: Data Connections download templates must use the canonical backend sales templates", () => {
  assert.match(templateConfig, /\/assets\/templates\/ceopro_sales_transaction_import_v1/,
    "TEMPLATE_HEADER_MISMATCH: frontend downloads ceopro-data-template assets, not the backend's canonical versioned sales templates.");
});

test("regression: upload UI size and supported-format claims must match backend limits", () => {
  assert.doesNotMatch(dropzone, /50\s*MB/i,
    "FRONTEND_BACKEND_VALIDATION_MISMATCH: upload dropzone still advertises 50 MB while backend defaults to 10 MiB.");
  assert.doesNotMatch(en.dataIngestion.supported, /Word|PNG|JPG|\.xls\b/i,
    "FRONTEND_BACKEND_VALIDATION_MISMATCH: English upload copy advertises formats the backend does not accept.");
  assert.doesNotMatch(ar.dataIngestion.supported, /Word|PNG|JPG|\.xls\b/i,
    "FRONTEND_BACKEND_VALIDATION_MISMATCH: Arabic upload copy advertises formats the backend does not accept.");
});

test("regression: actual template assets must be downloadable instead of preview links", () => {
  const download = ingestionApi.match(/downloadTemplate:[\s\S]*?\n  },/)?.[0] ?? "";
  assert.doesNotMatch(download, /preview:\s*true/,
    "TEMPLATE_DOWNLOAD_PREVIEW_ONLY: the current client exposes static preview asset URLs and no server-backed download/upload compatibility contract.");
});

test("regression: job and staging UI must query persisted backend data, not preview stubs", () => {
  assert.doesNotMatch(ingestionApi, /listJobs:\s*async\s*\(\)\s*=>\s*\(\{\s*jobs:\s*\[\],\s*preview:\s*true/,
    "FALSE_SUCCESS_UI: import history is an empty preview stub and cannot show persisted job state.");
  assert.doesNotMatch(ingestionApi, /reviewStagingRows:\s*async\s*\(\)\s*=>\s*\(\{\s*rows:\s*\[\],\s*preview:\s*true/,
    "STAGING_REVIEW_PREVIEW_ONLY: staging review returns a hard-coded empty preview.");
});

test("storage audit confirms business upload metadata is not included in storage capacity totals", () => {
  const storageUsage = capacity.match(/case "document_storage_mb":([\s\S]*?)(?:case |default:)/)?.[1] ?? "";
  assert.match(storageUsage, /rag_documents_metadata/);
  assert.doesNotMatch(storageUsage, /data_sources/);
  assert.match(repo, /file_size_bytes: input\.fileSizeBytes/);
});
