import assert from "node:assert/strict";
import { mock, test } from "node:test";
import { createHash } from "node:crypto";
let existing, calls, provider, recovered;
const reset = () => { existing = null; calls = { ai: 0, quota: 0, reserve: 0, stage: [], release: 0, recovery: 0 }; recovered = { recovered: true, status: "queued", stagedRowCount: 1503, addedRowCount: 503 }; };
const ErrorType = class extends Error {};
await mock.module("../../src/config/database.ts", { namedExports: { prisma: {} } });
await mock.module("../../src/modules/features/repo/usage.repo.ts", { namedExports: {
  FeatureUsageCapacityError: class extends Error {}, FeatureUsageUnavailableError: class extends Error {},
  getFeatureAccessInfo: async () => ({ subscription: {}, planFeature: {} }),
  getRemainingUsage: async () => { calls.quota++; return { remaining: null, isExceeded: false }; },
  reserveFeatureUsageInTransaction: async () => {}
} });
await mock.module("../../src/modules/dataconnection/repo/dataconnection.repo.ts", { namedExports: {
  BUSINESS_FILE_EXTRACTION_LEASE_MS: 900000,
  ConnectedSourceCapacityError: ErrorType, DataSourceNotFoundError: ErrorType, DataSourceReconnectRequiredError: ErrorType,
  DuplicateDataSourceError: ErrorType, IngestionJobNotFoundError: ErrorType, IngestionJobNotRetryableError: ErrorType,
  dataManagementRepo: {
    findBusinessFileImportByHash: async (tenant, user, hash) => { assert.equal(tenant, "tenant"); assert.equal(user, "user"); assert.match(hash, /^[a-f0-9]{64}$/); return existing; },
    reserveBusinessFileImport: async () => { calls.reserve++; return { duplicate: false, sourceId: "source", jobId: "job" }; },
    recordBusinessFileIngestion: async (input) => { calls.stage.push(input); return { stagedRowCount: input.rowOutcomes.length }; },
    markBusinessFileExtractionFailed: async () => { calls.release++; },
    completeBusinessCsvImport: async () => { calls.recovery++; return recovered; }
  }
} });
await mock.module("../../src/modules/dataconnection/client/ingestion.client.ts", { namedExports: {
  uploadExtractionFile: async () => { calls.ai++; return provider; }
} });
const { dataConnectionService } = await import("../../src/modules/dataconnection/service/dataconnection.service.ts");
const header = "product_name,quantity,unit_price,currency,transaction_date";
const rows = Array.from({ length: 1503 }, () => "Orange Juice 1L,2,2.95,JOD,2026-10-08").join("\n");
const file = (name, text) => { const buffer = Buffer.from(text); return { tenantId: "tenant", userId: "user", file: { originalname: name, mimetype: "text/csv", size: buffer.length, buffer } }; };
test("full CSV reaches staging directly, keeps exact file deduplication and reserves usage once", async () => {
  reset(); const input = file("sales.csv", `${header}\n${rows}`);
  const result = await dataConnectionService.uploadExtraction(input);
  assert.equal(calls.ai, 0); assert.equal(calls.reserve, 1); assert.equal(calls.quota, 1);
  assert.equal(calls.stage[0].rowOutcomes.length, 1503); assert.equal(calls.stage[0].extractionMethod, "canonical_csv");
  assert.equal(calls.stage[0].contentSha256, createHash("sha256").update(input.file.buffer).digest("hex"));
  assert.equal(result.source_rows_total, 1503); assert.equal(result.staged_row_count, 1503); assert.equal(result.import_complete, true);
});
test("invalid final CSV record fails before a reservation, AI call or staging write", async () => {
  reset(); await assert.rejects(dataConnectionService.uploadExtraction(file("sales.csv", `${header}\n${rows}\nTea,-1,3,JOD,2026-10-08`)), (error) => error.code === "INVALID_FILE_UPLOAD");
  assert.equal(calls.reserve, 0); assert.equal(calls.ai, 0); assert.equal(calls.stage.length, 0);
});
test("same-file partial recovery bypasses new charges and reports genuine added rows", async () => {
  reset(); existing = { sourceId: "source", jobId: "job", status: "completed", stagedRowCount: 1000, rowsProcessed: 1000, rowsFailed: 0, rowsPartial: 0, config: { rows_truncated_to_limit: true } };
  const result = await dataConnectionService.uploadExtraction(file("sales.csv", `${header}\n${rows}`));
  assert.equal(calls.recovery, 1); assert.equal(calls.quota, 0); assert.equal(calls.reserve, 0); assert.equal(calls.ai, 0);
  assert.equal(result.duplicate, false); assert.equal(result.recovered, true); assert.equal(result.added_row_count, 503); assert.equal(result.staged_row_count, 1503);
  existing.stagedRowCount = 1503; existing.config.rows_truncated_to_limit = false;
  assert.equal((await dataConnectionService.uploadExtraction(file("sales.csv", `${header}\n${rows}`))).duplicate, true);
});
test("AI truncation for a PDF releases the reservation and never stages a subset", async () => {
  reset(); provider = { rows_truncated_to_limit: true };
  await assert.rejects(dataConnectionService.uploadExtraction(file("sales.pdf", "%PDF-1.7\n")), (error) => error.code === "INVALID_FILE_UPLOAD");
  assert.equal(calls.ai, 1); assert.equal(calls.stage.length, 0); assert.equal(calls.release, 1);
});
