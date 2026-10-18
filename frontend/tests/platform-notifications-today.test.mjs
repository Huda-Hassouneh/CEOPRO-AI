import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { can } from "../src/features/platform-admin/permissions/platformPermissions.js";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("notification bell permission follows backend-provided notifications.read", () => {
  const owner = {
    status: "active",
    role: "owner",
    roleKey: "owner",
    permissions: { all: true }
  };
  const allowedAdmin = {
    status: "active",
    role: "admin",
    roleKey: "admin",
    permissions: { "notifications.read": true }
  };
  const deniedAdmin = {
    status: "active",
    role: "admin",
    roleKey: "admin",
    permissions: { "billing.read": true }
  };

  assert.equal(can(owner, "notifications.read"), true);
  assert.equal(can(allowedAdmin, "notifications.read"), true);
  assert.equal(can(deniedAdmin, "notifications.read"), false);
});

test("AdminContext forwards React Query polling/focus options", async () => {
  const code = await read("../src/features/platform-admin/components/AdminContext.jsx");

  assert.match(code, /export function useAdminQuery\(/);
  assert.match(code, /useQuery\(\{[\s\S]*\.\.\.options,/);
  assert.match(code, /retry:\s*options\.retry\s*\?\?\s*false/);
  assert.match(code, /enabled:\s*options\.enabled\s*\?\?\s*true/);
});

test("platformAdminApi exposes the exact five notification API operations", async () => {
  const code = await read("../src/features/platform-admin/api/platformAdminApi.js");

  assert.match(code, /notifications:\s*Object\.freeze\(\{/);
  assert.match(code, /httpClient\.get\(`\$\{base\}\/notifications`/);
  assert.match(code, /httpClient\.get\(`\$\{base\}\/notifications\/unread-count`/);
  assert.match(code, /httpClient\.post\(\s*`\$\{base\}\/notifications\/\$\{encodeURIComponent\(id\)\}\/read`/s);
  assert.match(code, /httpClient\.post\(\s*`\$\{base\}\/notifications\/\$\{encodeURIComponent\(id\)\}\/archive`/s);
  assert.match(code, /httpClient\.post\(`\$\{base\}\/notifications\/read-all`\)/);
});

test("Platform Admin bell uses real notification APIs rather than audit logs", async () => {
  const code = await read("../src/features/platform-admin/layout/PlatformAdminLayout.jsx");

  assert.match(code, /admin\.can\(["']notifications\.read["']\)/);
  assert.match(code, /useAdminQuery\(\s*["']notifications["']/s);
  assert.match(code, /useAdminQuery\(\s*["']notifications\/unread-count["']/s);
  assert.doesNotMatch(
    code,
    /const\s+notifications\s*=\s*useAdminQuery\(\s*["']audit-logs["']/s
  );
});

test("notification polling is 30 seconds and refreshes on window focus", async () => {
  const code = await read("../src/features/platform-admin/layout/PlatformAdminLayout.jsx");

  const matches = code.match(/refetchInterval:\s*30_000/g) ?? [];
  assert.ok(matches.length >= 2, "list and unread-count should both poll every 30s");

  const focusMatches = code.match(/refetchOnWindowFocus:\s*true/g) ?? [];
  assert.ok(
    focusMatches.length >= 2,
    "list and unread-count should both refetch on window focus"
  );
});

test("layout reads the actual backend success-response envelope", async () => {
  const code = await read("../src/features/platform-admin/layout/PlatformAdminLayout.jsx");

  assert.match(
    code,
    /notifications\.data\?\.data\?\.items\s*\?\?\s*\[\]/
  );
  assert.match(
    code,
    /unreadNotifications\.data\?\.data\?\.unreadCount\s*\?\?\s*0/
  );
});

test("bell actions use mark-read, archive and read-all APIs", async () => {
  const code = await read("../src/features/platform-admin/layout/PlatformAdminLayout.jsx");

  assert.match(code, /platformAdminApi\.notifications\.markRead\(/);
  assert.match(code, /platformAdminApi\.notifications\.archive\(/);
  assert.match(code, /platformAdminApi\.notifications\.readAll\(/);
});

test("notification styling is scoped so the profile popover is not redesigned", async () => {
  const layout = await read("../src/features/platform-admin/layout/PlatformAdminLayout.jsx");
  const css = await read("../src/features/platform-admin/styles/PlatformAdmin.css");

  assert.match(
    layout,
    /className=["']pa-popover pa-notification-popover["']/
  );
  assert.match(
    layout,
    /className=["']pa-popover-content pa-notification-popover-content["']/
  );
  assert.match(css, /\.pa-notification-popover-content\s*\{/);
  assert.match(
    css,
    /\.pa-notification-popover-content[\s\S]*\.pa-notification-item[\s\S]*>\s*button[\s\S]*width:\s*auto/s
  );
});
