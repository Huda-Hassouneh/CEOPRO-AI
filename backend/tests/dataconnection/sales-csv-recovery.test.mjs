import assert from "node:assert/strict";
import { mock, test } from "node:test";
import { extractCompleteSalesCsv } from "../../src/modules/dataconnection/service/sales-csv-import.ts";
const outcomes = extractCompleteSalesCsv("sales.csv", Buffer.from("product_name,quantity,unit_price,currency,transaction_date,order_id\nTea,2,3.25,JOD,2026-10-08,A\nTea,2,3.25,JOD,2026-10-08,B\nTea,2,3.25,JOD,2026-10-08,C")).summary.row_outcomes;
let state, operations, options, quotaCalls = 0;
const reset = () => {
  state = { status: "COMPLETED", config: { content_sha256: "hash", extraction_usage_reservation_status: "committed", rows_truncated_to_limit: true },
    rows: [{ raw_payload_json: outcomes[0].parse_result.typed_fields, validation_status: "COMMITTED", committed_table: "transactions", committed_record_id: "original-sale" }] };
  operations = []; quotaCalls = 0;
};
const tx = {
  $queryRaw: async (parts, ...values) => {
    const sql = parts.join("?"); operations.push({ sql, values });
    return sql.includes("FOR UPDATE") ? [{ job_status: state.status }] : [];
  },
  $executeRawUnsafe: async (sql, lock) => { operations.push({ sql, lock }); },
  data_sources: {
    findFirst: async ({ where }) => { assert.equal(where.tenant_id, "tenant"); assert.equal(where.source_id, "source"); assert.equal(where.collector_config.equals, "hash"); return { collector_config: state.config }; },
    update: async ({ where, data }) => { assert.equal(where.tenant_id_source_id.tenant_id, "tenant"); state.config = data.collector_config; }
  },
  import_staging_rows: {
    count: async ({ where }) => { assert.deepEqual(where, { tenant_id: "tenant", job_id: "job" }); return state.rows.length; },
    findMany: async ({ orderBy }) => { assert.deepEqual(orderBy, { staging_row_id: "asc" }); return state.rows; },
    createMany: async ({ data }) => { for (const row of data) { assert.equal(row.tenant_id, "tenant"); assert.equal(row.job_id, "job"); } state.rows.push(...data); }
  },
  ingestion_jobs: { update: async ({ where, data }) => { assert.equal(where.tenant_id_job_id.tenant_id, "tenant"); assert.equal(data.rows_processed, undefined); state.status = data.job_status; } },
  transactions: { create: async () => { throw new Error("Recovery must not recreate committed transactions."); } }
};
let tail = Promise.resolve();
await mock.module("../../src/config/database.ts", { namedExports: { prisma: { $transaction: (work, opts) => {
  // Serialize transaction callbacks to model the lock; restore state on rollback.
  const result = tail.then(async () => { options = opts; const before = structuredClone(state); try { return await work(tx); } catch (error) { state = before; throw error; } });
  tail = result.catch(() => {}); return result;
} } } });
await mock.module("../../src/modules/features/repo/usage.repo.ts", { namedExports: {
  getConnectedDataSourceCapacityInTransaction: async () => {},
  releaseFeatureUsageInTransaction: async () => { quotaCalls++; },
  reserveFeatureUsageInTransaction: async () => { quotaCalls++; }
} });
const { dataManagementRepo } = await import("../../src/modules/dataconnection/repo/dataconnection.repo.ts");
const input = { tenantId: "tenant", userId: "user", sourceId: "source", jobId: "job", contentSha256: "hash", rowOutcomes: outcomes };
test("recovery appends only missing rows under tenant, hash and worker job locks, without charging again", async () => {
  reset(); const original = structuredClone(state.rows[0]);
  const result = await dataManagementRepo.completeBusinessCsvImport(input);
  assert.equal(result.recovered, true); assert.equal(result.addedRowCount, 2); assert.equal(state.rows.length, 3);
  assert.deepEqual(state.rows[0], original); assert.equal(state.rows[1].validation_status, "PENDING");
  assert.equal(state.config.rows_truncated_to_limit, false); assert.equal(state.config.source_rows_total, 3);
  assert.equal(state.status, "QUEUED"); assert.equal(quotaCalls, 0);
  assert.deepEqual(operations[0].values, ["tenant", "user"]);
  assert.match(operations[1].sql, /pg_advisory_xact_lock/); assert.equal(operations[1].lock, "manual-business-file:tenant:hash");
  assert.match(operations[2].sql, /FOR UPDATE/); assert.ok(operations[2].values.includes("tenant"));
  assert.deepEqual(options, { maxWait: 10000, timeout: 180000 });
});
test("concurrent recovery requests append the suffix once", async () => {
  reset(); const result = await Promise.all([dataManagementRepo.completeBusinessCsvImport(input), dataManagementRepo.completeBusinessCsvImport(input)]);
  assert.equal(result.filter((value) => value.recovered).length, 1); assert.equal(state.rows.length, 3); assert.equal(quotaCalls, 0);
});
test("active, edited or uncharged imports cannot be partially changed by recovery", async () => {
  for (const mutate of [() => { state.status = "PROCESSING"; }, () => { state.rows[0].raw_payload_json = { ...state.rows[0].raw_payload_json, order_id: "edited" }; }, () => { state.config.extraction_usage_reservation_status = "reserved"; }]) {
    reset(); mutate(); const before = structuredClone(state);
    await assert.rejects(dataManagementRepo.completeBusinessCsvImport(input)); assert.deepEqual(state, before); assert.equal(quotaCalls, 0);
  }
});
