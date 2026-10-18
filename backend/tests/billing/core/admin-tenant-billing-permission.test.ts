import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const migration = readFileSync(
  new URL(
    "../../../prisma/migrations/20261005102000_grant_tenant_admin_manage_billing/migration.sql",
    import.meta.url
  ),
  "utf8"
);

const subscriptionRoutes = readFileSync(
  new URL("../../../src/modules/subscription/route/subscriptions.route.ts", import.meta.url),
  "utf8"
);

test("tenant admin role is granted canonical tenant billing management", () => {
  assert.match(migration, /WHERE role_key = 'admin'/);
  assert.match(migration, /"manage_billing"\s*:\s*true/);
});

test("tenant checkout keeps the tenant-scoped manage_billing boundary", () => {
  assert.match(
    subscriptionRoutes,
    /"\/checkout"[\s\S]*requirePermission\("manage_billing"\)/
  );
});
