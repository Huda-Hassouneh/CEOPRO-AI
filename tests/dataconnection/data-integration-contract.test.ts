import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { validateCreateDataSource } from "../../src/modules/dataconnection/validators/dataconnection.validation.js";
import { parseSalesStagingRow } from "../../src/modules/dataconnection/service/sales-staging-row.js";
import { validateExtractionUpload } from "../../src/modules/dataconnection/types/dataconnection.validation.js";

const read = (file: string) => readFileSync(new URL(`../../${file}`, import.meta.url), "utf8");

test("Data Connections endpoints enforce authentication and separate upload from source registration", () => {
  const route = read("src/modules/dataconnection/route/dataconnection.route.ts");
  const app = read("src/app.ts");
  assert.match(route, /router\.use\(authenticateUser, requireTenant\)/);
  assert.match(route, /requireEntitlement\("document_extraction"\)/);
  assert.match(route, /requireEntitlement\("data_integration"\)/);
  assert.match(route, /router\.get\(\s*"\/",\s*dataConnectionController\.getConnectionsOverview/);
  assert.match(app, /app\.use\("\/", dataconnection\)/);
  assert.match(route, /router\.post\(\s*"\/sources"/);
  assert.doesNotMatch(route, /router\.post\("\/:sourceId\/(?:sync|test|reconnect)/);
});

test("manual upload validates quota, reserves it atomically with its job, then stages extracted rows", () => {
  const service = read("src/modules/dataconnection/service/dataconnection.service.ts");
  const repo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
  assert.match(service, /validateExtractionUpload\(input\.file\)/);
  assert.match(service, /getRemainingUsage\([\s\S]*?"document_extraction"\s*\)/);
  assert.doesNotMatch(service, /featureCode: "document_storage_mb"/);
  assert.ok(service.indexOf("reserveBusinessFileImport({") < service.indexOf("uploadExtractionFile({"));
  assert.ok(service.indexOf("uploadExtractionFile({") < service.indexOf("recordBusinessFileIngestion({"));
  assert.doesNotMatch(service, /incrementUsage\(input\.tenantId, "document_extraction"/);
  assert.match(repo, /reserveFeatureUsageInTransaction\([\s\S]*?"document_extraction"[\s\S]*?input\.extractionUsageKb/);
  assert.match(repo, /releaseFeatureUsageInTransaction\([\s\S]*?"document_extraction"/);
  assert.match(repo, /extraction_usage_reservation_status: "committed"/);
  assert.match(service, /staged_row_count: persisted\.stagedRowCount/);
  assert.match(service, /promotion: null/);
});

test("manual uploads reserve an inactive extraction job, then queue staged rows transactionally", () => {
  const repo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
  const reservation = repo.match(/reserveBusinessFileImport: async[\s\S]*?markBusinessFileExtractionFailed/)?.[0] ?? "";
  const writeBlock = repo.match(/recordBusinessFileIngestion: async[\s\S]*?\n  },\n\n  createPersistentSource/)?.[0] ?? "";
  assert.match(reservation, /set_config\('app\.current_tenant_id'/);
  assert.match(reservation, /source_type: "documents"/);
  assert.match(reservation, /is_active: false/);
  assert.match(reservation, /job_status: "EXTRACTING"/);
  assert.match(writeBlock, /set_config\('app\.current_tenant_id'/);
  assert.match(writeBlock, /job_status: "QUEUED"/);
  assert.match(writeBlock, /import_staging_rows\.createMany/);
  assert.match(repo, /content_sha256/);
  assert.match(repo, /pg_advisory_xact_lock/);
});

test("worker promotes only PENDING rows transactionally and is bounded/retryable, but no record-level transaction dedupe key is used", () => {
  const worker = read("src/modules/dataconnection/repo/ingestion-worker.repo.ts");
  assert.match(worker, /INGESTION_WORKER_MAX_ATTEMPTS = 5/);
  assert.match(worker, /FOR UPDATE OF j SKIP LOCKED/);
  assert.match(worker, /validation_status: "PENDING"/);
  assert.match(worker, /tx\.transactions\.create/);
  assert.match(worker, /validation_status: "COMMITTED"/);
  assert.match(worker, /job_status: "COMPLETED"/);
  assert.match(worker, /Math\.min\(BASE_RETRY_MS \* 2 \*\* exponent, MAX_RETRY_MS\)/);
  const transactionInsert = worker.match(/tx\.transactions\.create\([\s\S]*?\n    \}\);/)?.[0] ?? "";
  assert.ok(transactionInsert, "transaction insert must remain visible for the import identity review");
  assert.doesNotMatch(transactionInsert, /external|invoice_id|order_id|idempot|source_record/);
});

test("product identity is tenant plus normalized English name, while repeated transaction rows can still duplicate", () => {
  const worker = read("src/modules/dataconnection/repo/ingestion-worker.repo.ts");
  const schema = read("prisma/schema.prisma");
  assert.match(worker, /productName\.trim\(\)\.toLocaleLowerCase\("en-US"\)/);
  assert.match(worker, /pg_advisory_xact_lock/);
  assert.match(worker, /p\.tenant_id = \$\{tenantId\}::uuid/);
  assert.match(worker, /validation_status: "PENDING"/);
  assert.match(schema, /model transactions \{[\s\S]*?sale_source\s+String/);
});

test("persistent source registration stores configuration only and treats active as registered, not verified", () => {
  const service = read("src/modules/dataconnection/service/dataconnection.service.ts");
  const repo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
  const creation = service.match(/createDataSource: async[\s\S]*?\n  \}\n\};/)?.[0] ?? "";
  const repoCreation = repo.match(/createPersistentSource: async[\s\S]*?setPersistentSourceActive/)?.[0] ?? "";
  assert.match(creation, /dataManagementRepo\.createPersistentSource/);
  assert.match(repoCreation, /getConnectedDataSourceCapacityInTransaction/);
  assert.match(repoCreation, /connection_credentials_vault: null/);
  assert.match(repoCreation, /is_active: true/);
  assert.doesNotMatch(creation, /testConnection|verifyCredentials|syncSource|uploadExtractionFile/);
});

test("Gradio extraction sends safe filename, base64 file bytes, and country/currency context with schema-validated response", () => {
  const client = read("src/modules/dataconnection/client/ingestion.client.ts");
  assert.match(client, /apiName: "extract_file"/);
  assert.match(client, /fileName,[\s\S]*?input\.file\.buffer\.toString\("base64"\),[\s\S]*?input\.countryCode \?\? "JO",[\s\S]*?input\.currency \?\? "JOD"/);
  assert.match(client, /service: "analytics"/);
  assert.match(client, /extractionResponseSchema\.safeParse\(payload\)/);
  assert.match(client, /malformed_response/);
  assert.match(client, /MAX_UPLOAD_SIZE_BYTES/);
});

test("registration validator accepts enumerated source types, persists public website URLs, and rejects secrets", () => {
  const valid = validateCreateDataSource({ name: "Shop store", sourceType: "SHOPIFY", metadata: { region: "JO" } });
  assert.equal(valid.success, true);
  if (valid.success) assert.equal(valid.data.syncFrequencyMinutes, 1440);
  for (const sourceType of ["shopify", "postgresql", "mysql", "sqlserver", "ga4"]) {
    assert.equal(validateCreateDataSource({ name: "source", sourceType }).success, true, sourceType);
  }
  const website = validateCreateDataSource({
    name: "public shop",
    sourceType: "website",
    sourceUrl: "https://shop.example.com/"
  });
  assert.equal(website.success, true);
  if (website.success) assert.equal(website.data.sourceUrl, "https://shop.example.com");
  assert.equal(validateCreateDataSource({ name: "", sourceType: "shopify" }).success, false);
  assert.equal(validateCreateDataSource({ name: "source", sourceType: "unknown" }).success, false);
  assert.equal(validateCreateDataSource({ name: "source", sourceType: "postgresql", metadata: { nested: { api_key: "secret" } } }).success, false);
  assert.equal(validateCreateDataSource({ name: "source", sourceType: "website", syncFrequencyMinutes: 0 }).success, false);
});

test("staging parser validates monetary precision, positive quantities, ISO currency and computes sales totals", () => {
  const valid = parseSalesStagingRow({ product_name: "زيت زيتون", quantity: 3, unit_price: "24.5", currency: "jod", transaction_date: "2026-08-30", discount_pct: "10" });
  assert.equal(valid.ok, true);
  if (valid.ok) {
    assert.equal(valid.value.totalPrice, "66.1500");
    assert.equal(valid.value.unitPrice, "24.5000");
    assert.equal(valid.value.currency, "JOD");
  }
  for (const invalid of [
    { product_name: "x", quantity: 0, unit_price: 1, currency: "JOD", transaction_date: "2026-08-30" },
    { product_name: "x", quantity: -1, unit_price: 1, currency: "JOD", transaction_date: "2026-08-30" },
    { product_name: "x", quantity: 1, unit_price: "1.12345", currency: "JOD", transaction_date: "2026-08-30" },
    { product_name: "x", quantity: 1, unit_price: 1, currency: "US", transaction_date: "2026-08-30" },
    { product_name: "x", quantity: 1, unit_price: 1, currency: "JOD", transaction_date: "2026-02-30" }
  ]) assert.equal(parseSalesStagingRow(invalid).ok, false);
});

test("upload preflight rejects duplicate canonical headings that could map one field ambiguously", () => {
  const headers = "product_name,quantity,unit_price,currency,transaction_date,product_name";
  const buffer = Buffer.from(`${headers}\nOlive Oil,1,2.50,JOD,2026-10-11,Conflicting Name\n`);
  const file = { originalname: "sales.csv", size: buffer.length, buffer };
  assert.equal(validateExtractionUpload(file), "TEMPLATE_MISMATCH");
});

test("future transaction dates are accepted because the persistence parser enforces ISO validity only", () => {
  const result = parseSalesStagingRow({ product_name: "Future sale", quantity: 1, unit_price: "1", currency: "JOD", transaction_date: "2099-01-01" });
  assert.equal(result.ok, true);
});

test("plan source and extraction limits and reset behavior are taken from current production catalog", () => {
  const plans = read("src/config/production-plans.ts");
  const catalog = read("src/modules/features/catalog.ts");
  const extraction = read("src/modules/dataconnection/service/dataconnection.service.ts");
  assert.match(plans, /limitFeature\("connected_data_sources", 1\)/);
  assert.match(plans, /limitFeature\("connected_data_sources", 5\)/);
  assert.match(plans, /limitFeature\("connected_data_sources", 20\)/);
  assert.match(plans, /limitFeature\("document_extraction", 51_200\)/);
  assert.match(plans, /limitFeature\("document_extraction", 512_000\)/);
  assert.match(plans, /limitFeature\("document_extraction", 2_097_152\)/);
  assert.match(extraction, /Math\.ceil\(input\.file\.size \/ 1024\)/);
  assert.match(catalog, /code: "document_extraction"[\s\S]*?resetCycle: ResetCycle\.billing_period/);
  assert.match(catalog, /code: "connected_data_sources"[\s\S]*?resetCycle: ResetCycle\.lifetime/);
});

test("manual file extraction is billed in rounded KB and transient uploads do not consume stored-document capacity", () => {
  const usage = read("src/modules/features/service/capacity.service.ts");
  const repo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
  const service = read("src/modules/dataconnection/service/dataconnection.service.ts");
  assert.match(usage, /case "document_storage_mb"[\s\S]*?rag_documents_metadata\.aggregate/);
  assert.match(repo, /source_type: "documents"/);
  assert.match(repo, /file_size_bytes: input\.fileSizeBytes/);
  assert.doesNotMatch(usage.match(/case "document_storage_mb"[\s\S]*?\n    }/)?.[0] ?? "", /data_sources|collector_config/);
  assert.doesNotMatch(service, /featureCode: "document_storage_mb"/);
});

test("source overview and frontend show configuration honestly and persist the submitted website URL", () => {
  const repo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
  const api = read("../frontend/src/features/data-connections/api/dataConnectionsApi.js");
  const page = read("../frontend/src/features/data-connections/pages/ConnectDataPage.jsx");
  const service = read("src/modules/dataconnection/service/dataconnection.service.ts");
  const validator = read("src/modules/dataconnection/types/dataconnection.validation.ts");
  assert.doesNotMatch(repo, /dataStatus:\s*"verified"/);
  assert.match(repo, /status: isDisconnected[\s\S]*?source\.is_active[\s\S]*?\? status[\s\S]*?: "paused"/);
  assert.match(repo, /sourceUrl: source\.source_url/);
  assert.match(api, /sourceType: "website",\s*sourceUrl: url/);
  assert.match(service, /sourceUrl: validation\.data\.sourceUrl/);
  assert.match(validator, /normalizeSourceUrl/);
  assert.match(page, /type !== "website"/);
  assert.match(page, /sourceConfigured/);
  assert.doesNotMatch(api, /previewDelay|connectGoogleAnalytics|prepareDatabase|reconnect|sync:/);
});

test("job details, staging review, retries, and published sales templates use real Node routes", () => {
  const api = read("../frontend/src/features/data-ingestion/api/ingestionApi.js");
  const connectionApi = read("../frontend/src/features/data-connections/api/dataConnectionsApi.js");
  const route = read("src/modules/dataconnection/route/dataconnection.route.ts");
  assert.match(api, /getJob: async/);
  assert.match(api, /reviewStagingRows: async/);
  assert.match(api, /updateStagingRow: async/);
  assert.match(api, /retryJob: async/);
  assert.match(api, /const kind = template\.kind \|\| 'sales'/);
  assert.match(route, /"\/templates\/sales\/:format"/);
  assert.match(connectionApi, /configureWebsite:[\s\S]*?httpClient\.post\("\/data-connection\/sources"/);
  assert.match(route, /router\.get\([\s\S]*?"\/jobs"/);
  assert.match(route, /router\.post\([\s\S]*?"\/jobs\/:jobId\/retry"/);
  assert.match(route, /router\.patch\([\s\S]*?"\/jobs\/:jobId\/staging\/:rowId"/);
});

test("the UI downloads the backend's canonical sales template", () => {
  const backendTemplate = read("src/modules/dataconnection/templates/ceopro_sales_transaction_import_v1.csv");
  const api = read("../frontend/src/features/data-ingestion/api/ingestionApi.js");
  const controller = read("src/modules/dataconnection/controller/dataconnection.controller.ts");
  assert.match(backendTemplate, /^product_name,quantity,unit_price,currency,transaction_date/m);
  assert.match(api, /const kind = template\.kind \|\| 'sales'/);
  assert.match(api, /data-connection\/templates\/\$\{kind\}\/\$\{format\}/);
  assert.match(controller, /ceopro_sales_transaction_import_v1\./);
});

test("business upload format and size validation matches the backend contract", () => {
  const validation = read("../frontend/src/features/data-ingestion/utils/fileValidation.js");
  const dropzone = read("../frontend/src/features/data-ingestion/components/FileUploadDropzone.jsx");
  assert.match(validation, /MAX_BUSINESS_UPLOAD_FILE_SIZE\s*=\s*10\s*\*\s*1024\s*\*\s*1024/);
  assert.match(validation, /BUSINESS_UPLOAD_EXTENSIONS[\s\S]*pdf\|csv\|xlsx\|xlsm/);
  assert.match(dropzone, /getInvalidBusinessUploadFile/);
  assert.match(dropzone, /BUSINESS_UPLOAD_FILE_TYPES/);
});

test("AI connectors stage/normalize records but do not call AI product-and-transaction promotion", (t) => {
  const aiRoot = process.env.AI_CODEBASE_DIR;
  const aiFile = (relative: string) => aiRoot
    ? join(aiRoot, relative)
    : new URL(`../../../../ai/unpacked/src/${relative}`, import.meta.url);
  if (!existsSync(aiFile("market_scraper/connector_sync.py"))) {
    t.skip("Optional AI snapshot is absent; set AI_CODEBASE_DIR to its src directory.");
    return;
  }
  const dbSync = readFileSync(aiFile("market_scraper/connector_sync.py"), "utf8");
  const apiSync = readFileSync(aiFile("market_scraper/api_connector_sync.py"), "utf8");
  const pipeline = readFileSync(aiFile("ai/extraction/ingestion_pipeline.py"), "utf8");
  assert.match(dbSync, /process_records\(/);
  assert.match(apiSync, /process_records\(/);
  assert.match(dbSync, /finish_ingestion_job\([\s\S]*?status="COMPLETED"/);
  assert.match(apiSync, /finish_ingestion_job\([\s\S]*?status="COMPLETED"/);
  assert.doesNotMatch(dbSync, /promote_ingested_rows/);
  assert.doesNotMatch(apiSync, /promote_ingested_rows/);
  assert.match(pipeline, /import_staging_rows|extracted_entity|staging/i);
});

test("RLS and worker role boundaries are defined in migrations; test runtime remains read-only unless explicitly provisioned", () => {
  const migration = read("prisma/migrations/20261006120000_business_data_ingestion_worker/migration.sql");
  const baseline = read("prisma/migrations/20260800000000_baseline/migration.sql");
  assert.match(migration, /ceopro_ingestion_worker/);
  assert.match(migration, /GRANT[\s\S]*import_staging_rows/);
  assert.match(baseline, /ALTER TABLE data_sources FORCE ROW LEVEL SECURITY/);
  assert.match(baseline, /ALTER TABLE ingestion_jobs FORCE ROW LEVEL SECURITY/);
  assert.match(baseline, /ALTER TABLE import_staging_rows FORCE ROW LEVEL SECURITY/);
});
