import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

async function migration(path: string) {
  return readFile(new URL(path, import.meta.url), "utf8");
}

test("platform notification storage enforces tenant-scoped dedupe and FORCE RLS", async () => {
  const sql = await migration(
    "../../prisma/migrations/20261003000000_platform_admin_notifications/migration.sql"
  );

  assert.match(
    sql,
    /CREATE UNIQUE INDEX "platform_notification_outbox_tenant_dedupe_key"[\s\S]*"tenant_id"[\s\S]*"dedupe_key"/
  );
  assert.match(sql, /ALTER TABLE "platform_notifications"[\s\S]*FORCE ROW LEVEL SECURITY/);
  assert.match(sql, /ALTER TABLE "platform_notification_receipts"[\s\S]*FORCE ROW LEVEL SECURITY/);
  assert.match(sql, /ALTER TABLE "platform_notification_outbox"[\s\S]*FORCE ROW LEVEL SECURITY/);
});

test("dedicated worker role is non-superuser, non-BYPASSRLS, and narrowly granted", async () => {
  const sql = await migration(
    "../../prisma/migrations/20261003193000_platform_notification_worker_role/migration.sql"
  );

  assert.match(sql, /CREATE ROLE ceopro_notification_worker/);
  assert.match(sql, /NOSUPERUSER/);
  assert.match(sql, /NOCREATEDB/);
  assert.match(sql, /NOCREATEROLE/);
  assert.match(sql, /NOBYPASSRLS/);

  assert.match(
    sql,
    /GRANT SELECT, UPDATE[\s\S]*platform_notification_outbox[\s\S]*ceopro_notification_worker/
  );
  assert.match(
    sql,
    /GRANT SELECT, INSERT[\s\S]*platform_notifications[\s\S]*ceopro_notification_worker/
  );
  assert.match(
    sql,
    /GRANT INSERT[\s\S]*platform_notification_receipts[\s\S]*ceopro_notification_worker/
  );

  assert.doesNotMatch(sql, /GRANT\s+ALL/i);
  assert.doesNotMatch(sql, /GRANT\s+DELETE/i);
  assert.doesNotMatch(sql, /GRANT[^;]*subscriptions[^;]*ceopro_notification_worker/i);
});
