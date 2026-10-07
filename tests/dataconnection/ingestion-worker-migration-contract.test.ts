import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const read = (path: string) => readFile(new URL(path, import.meta.url), "utf8");

test("ingestion worker has a dedicated non-privileged PostgreSQL identity", async () => {
  const sql = await read(
    "../../prisma/migrations/20261006120000_business_data_ingestion_worker/migration.sql"
  );

  assert.match(sql, /CREATE ROLE ceopro_ingestion_worker/);
  assert.match(sql, /NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS/);
  assert.match(sql, /GRANT SELECT, UPDATE ON TABLE ingestion_jobs, import_staging_rows/);
  assert.match(sql, /GRANT SELECT, INSERT ON TABLE products/);
  assert.match(sql, /GRANT INSERT ON TABLE transactions/);
  assert.doesNotMatch(sql, /GRANT\s+ALL/i);
  assert.doesNotMatch(sql, /GRANT\s+DELETE/i);
});

test("job and staging access is restricted to active tenants and document imports", async () => {
  const sql = await read(
    "../../prisma/migrations/20261006120000_business_data_ingestion_worker/migration.sql"
  );

  assert.match(sql, /business_type IS DISTINCT FROM 'platform'/);
  assert.match(sql, /deleted_at IS NULL/);
  assert.match(sql, /source_type = 'documents'/);
  assert.match(sql, /CREATE POLICY ingestion_worker_staging_read/);
  assert.match(sql, /CREATE POLICY ingestion_worker_transaction_insert/);
  assert.match(sql, /sale_source = 'IMPORT'/);
});
