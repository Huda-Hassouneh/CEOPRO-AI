import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
  assert.match(app, /app\.use\("\/", dataconnection\)/);
  assert.match(route, /router\.post\(\s*"\/sources"/);
  assert.doesNotMatch(route, /router\.post\("\/:sourceId\/(?:sync|test|reconnect)/);
});

test("manual upload validates file and quota before AI; persists local job/staging before usage increment", () => {
  const service = read("src/modules/dataconnection/service/dataconnection.service.ts");
  assert.match(service, /validateExtractionUpload\(input\.file\)/);
  assert.match(service, /getRemainingUsage\([\s\S]*?"document_extraction"\s*\)/);
  assert.match(service, /assertFeatureCapacity\([\s\S]*?featureCode: "document_storage_mb"/);
  assert.ok(service.indexOf("uploadExtractionFile({") < service.indexOf("recordBusinessFileIngestion({"));
  assert.ok(service.indexOf("recordBusinessFileIngestion({") < service.indexOf("incrementUsage(input.tenantId, \"document_extraction\""));
  assert.match(service, /staged_row_count: persisted\.stagedRowCount/);
  assert.match(service, /promotion: null/);
});

test("manual file source is inactive, job is QUEUED, and extracted outcomes are staged in one tenant transaction", () => {
  const repo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
  const writeBlock = repo.match(/recordBusinessFileIngestion: async[\s\S]*?\n  },\n\n  createPersistentSource/)?.[0] ?? "";
  assert.match(writeBlock, /set_config\('app\.current_tenant_id'/);
  assert.match(writeBlock, /source_type: "documents"/);
  assert.match(writeBlock, /is_active: false/);
  assert.match(writeBlock, /job_status: "QUEUED"/);
  assert.match(writeBlock, /import_staging_rows\.createMany/);
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
  const repoCreation = repo.match(/createPersistentSource: async[\s\S]*?\n  },\n\n  countActivePersistentSources/)?.[0] ?? "";
  assert.match(creation, /assertFeatureCapacity\([\s\S]*?featureCode: "connected_data_sources"/);
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

test("registration validator accepts only enumerated source types and rejects secret-like metadata recursively", () => {
  const valid = validateCreateDataSource({ name: "Shop store", sourceType: "SHOPIFY", metadata: { region: "JO" } });
  assert.equal(valid.success, true);
  if (valid.success) assert.equal(valid.data.syncFrequencyMinutes, 1440);
  for (const sourceType of ["shopify", "postgresql", "mysql", "sqlserver", "ga4", "website"]) {
    assert.equal(validateCreateDataSource({ name: "source", sourceType }).success, true, sourceType);
  }
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

test("upload preflight does not validate multipart MIME and currently accepts duplicate canonical headings", () => {
  const headers = "product_name,quantity,unit_price,currency,transaction_date,product_name";
  const buffer = Buffer.from(`${headers}\nOlive Oil,1,2.50,JOD,2026-10-11,Conflicting Name\n`);
  const file = { originalname: "sales.csv", size: buffer.length, buffer, mimetype: "image/png" };
  assert.equal(validateExtractionUpload(file), null);
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

test("manual file usage is billed in rounded KB, but storage capacity does not count manual upload metadata", () => {
  const usage = read("src/modules/features/service/capacity.service.ts");
  const repo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
  assert.match(usage, /case "document_storage_mb"[\s\S]*?rag_documents_metadata\.aggregate/);
  assert.match(repo, /source_type: "documents"/);
  assert.match(repo, /file_size_bytes: input\.fileSizeBytes/);
  assert.doesNotMatch(usage.match(/case "document_storage_mb"[\s\S]*?\n    }/)?.[0] ?? "", /data_sources|collector_config/);
});

test("source overview exposes unverified 'verified' dataStatus and frontend sync/database actions can report false success", () => {
  const repo = read("src/modules/dataconnection/repo/dataconnection.repo.ts");
  const api = read("../frontend/src/features/data-connections/api/dataConnectionsApi.js");
  const page = read("../frontend/src/features/data-connections/pages/ConnectDataPage.jsx");
  const service = read("src/modules/dataconnection/service/dataconnection.service.ts");
  const validator = read("src/modules/dataconnection/validators/dataconnection.validation.ts");
  assert.match(repo, /dataStatus: "verified"/);
  assert.match(api, /connectGoogleAnalytics: async[\s\S]*?\/data-connection\/\$\{sourceId\}\/sync/);
  assert.match(api, /prepareDatabase: \(payload\) =>[\s\S]*?preview: true[\s\S]*?connected: false/);
  assert.match(api, /sync: \(sourceId\) =>[\s\S]*?ok: false[\s\S]*?available: false/);
  assert.match(page, /await dataConnectionsApi\.sync\(source\.id\);[\s\S]*?syncStarted/);
  assert.match(page, /await dataConnectionsApi\.prepareDatabase\(\{ companyId \}\);[\s\S]*?sourceConnected/);
  assert.match(page, /connectGoogleAnalytics\(\{ companyId \}\)/);
  assert.match(api, /configureWebsite:[\s\S]*?sourceType: "website",[\s\S]*?url,/);
  assert.match(service, /metadata: validation\.data\.metadata \?\? \{\}/);
  assert.doesNotMatch(validator, /value\.url|url:\s*value/);
});

test("Data Connections frontend job review, template download and status actions retain preview/missing-route behavior", () => {
  const api = read("../frontend/src/features/data-ingestion/api/ingestionApi.js");
  const connectionApi = read("../frontend/src/features/data-connections/api/dataConnectionsApi.js");
  const route = read("src/modules/dataconnection/route/dataconnection.route.ts");
  assert.match(api, /listJobs: async \(\) => \(\{ jobs: \[\], preview: true \}\)/);
  assert.match(api, /reviewStagingRows: async \(\) => \(\{ rows: \[\], preview: true \}\)/);
  assert.match(api, /downloadTemplate: async[\s\S]*?preview: true/);
  assert.match(connectionApi, /configureWebsite:[\s\S]*?httpClient\.post\("\/data-connection\/sources"/);
  assert.match(connectionApi, /reconnect: \(sourceId\) =>[\s\S]*?ok: false/);
  assert.doesNotMatch(route, /router\.post\("\/:sourceId\/(?:sync|test|reconnect)/);
});

test("advertised downloadable CSV template does not match the backend's required sales import template", () => {
  const uiTemplate = read("../frontend/public/assets/templates/ceopro-data-template.csv");
  const backendTemplate = read("src/modules/dataconnection/templates/ceopro_sales_transaction_import_v1.csv");
  assert.match(uiTemplate, /^Field,Value,Date,Notes/m);
  assert.match(backendTemplate, /^product_name,quantity,unit_price,currency,transaction_date/m);
  assert.notEqual(uiTemplate.split(/\r?\n/)[0], backendTemplate.split(/\r?\n/)[0]);
});

test("AI connectors stage/normalize records but do not call AI product-and-transaction promotion", () => {
  const dbSync = read("../ai/src/market_scraper/connector_sync.py");
  const apiSync = read("../ai/src/market_scraper/api_connector_sync.py");
  const pipeline = read("../ai/src/ai/extraction/ingestion_pipeline.py");
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
