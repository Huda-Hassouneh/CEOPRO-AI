import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

async function migration(path: string) {
  return readFile(new URL(path, import.meta.url), "utf8");
}

test("tenant notification storage uses composite tenant membership and FORCE RLS", async () => {
  const sql = await migration(
    "../../../prisma/migrations/20261004100000_tenant_notifications/migration.sql"
  );

  assert.match(
    sql,
    /FOREIGN KEY \("tenant_id", "recipient_user_id"\)[\s\S]*REFERENCES "tenant_users"\("tenant_id", "user_id"\)/
  );
  assert.match(
    sql,
    /CREATE UNIQUE INDEX "tenant_notification_outbox_tenant_dedupe_key"[\s\S]*"tenant_id"[\s\S]*"dedupe_key"/
  );
  assert.match(
    sql,
    /ALTER TABLE "tenant_notifications"[\s\S]*FORCE ROW LEVEL SECURITY/
  );
  assert.match(
    sql,
    /ALTER TABLE "tenant_notification_receipts"[\s\S]*FORCE ROW LEVEL SECURITY/
  );
  assert.match(
    sql,
    /ALTER TABLE "tenant_notification_outbox"[\s\S]*FORCE ROW LEVEL SECURITY/
  );
});

test("tenant worker access stays narrow and the platform producer uses ceopro_app, not the worker identity", async () => {
  const sql = await migration(
    "../../../prisma/migrations/20261004103000_tenant_notification_worker_access/migration.sql"
  );

  assert.match(
    sql,
    /GRANT SELECT, UPDATE[\s\S]*tenant_notification_outbox[\s\S]*ceopro_notification_worker/
  );
  assert.match(
    sql,
    /GRANT SELECT, INSERT[\s\S]*tenant_notifications[\s\S]*ceopro_notification_worker/
  );
  assert.match(
    sql,
    /GRANT INSERT[\s\S]*tenant_notification_receipts[\s\S]*ceopro_notification_worker/
  );
  assert.match(
    sql,
    /CREATE POLICY tenant_notification_outbox_platform_source_insert[\s\S]*TO ceopro_app/
  );
  assert.match(sql, /billing\.manage/);
  assert.doesNotMatch(sql, /GRANT\s+ALL/i);
  assert.doesNotMatch(sql, /GRANT\s+DELETE/i);
});
