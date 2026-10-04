import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

const readJson = async (path) => JSON.parse(await read(path));

test("tenant notifications API exposes the exact five backend operations", async () => {
  const code = await read("../src/features/notifications/api/notificationsApi.js");

  assert.match(code, /const base = ["']\/notifications["']/);
  assert.match(code, /httpClient\.get\(base/);
  assert.match(code, /httpClient\.get\(`\$\{base\}\/unread-count`/);
  assert.match(code, /httpClient\.post\(`\$\{base\}\/\$\{encodeURIComponent\(id\)\}\/read`\)/);
  assert.match(code, /httpClient\.post\(`\$\{base\}\/\$\{encodeURIComponent\(id\)\}\/archive`\)/);
  assert.match(code, /httpClient\.post\(`\$\{base\}\/read-all`\)/);
});

test("tenant notification queries are tenant/user scoped and poll every 30 seconds", async () => {
  const code = await read("../src/features/notifications/hooks/useTenantNotifications.js");

  assert.match(code, /const POLL_INTERVAL_MS = 30_000/);
  assert.match(code, /"tenant-notifications",\s*tenantId,\s*recipientKey/s);

  const intervalMatches = code.match(/refetchInterval:\s*POLL_INTERVAL_MS/g) ?? [];
  assert.equal(intervalMatches.length, 2);

  const focusMatches = code.match(/refetchOnWindowFocus:\s*true/g) ?? [];
  assert.equal(focusMatches.length, 2);
});

test("hook reads the backend success-response envelope", async () => {
  const code = await read("../src/features/notifications/hooks/useTenantNotifications.js");

  assert.match(code, /listQuery\.data\?\.data\?\.items\s*\?\?\s*\[\]/);
  assert.match(code, /unreadQuery\.data\?\.data\?\.unreadCount\s*\?\?\s*0/);
});

test("notification mutations invalidate tenant notification queries", async () => {
  const code = await read("../src/features/notifications/hooks/useTenantNotifications.js");

  assert.match(code, /mutationFn:\s*notificationsApi\.markRead/);
  assert.match(code, /mutationFn:\s*notificationsApi\.archive/);
  assert.match(code, /mutationFn:\s*notificationsApi\.readAll/);
  assert.match(code, /invalidateQueries\(\{[\s\S]*queryKeys\.root\(tenantId, recipientKey\)/);
});

test("tenant topbar uses the real notification hook and renders unread state", async () => {
  const code = await read("../src/shared/components/layout/Topbar.jsx");

  assert.match(code, /useTenantNotifications\(\{ limit: 5 \}\)/);
  assert.match(code, /unreadCount > 0/);
  assert.match(code, /notifications\.map\(\(notification\)/);
  assert.doesNotMatch(code, /businessShell\.notifications\.preview/);
});

test("notification actions wire read, archive and read-all behavior", async () => {
  const code = await read("../src/shared/components/layout/Topbar.jsx");

  assert.match(code, /markRead\(notification\.id\)/);
  assert.match(code, /archive\(notificationId\)/);
  assert.match(code, /onClick=\{\(\) => readAll\(\)\}/);
});

test("CUSTOM_PLAN_OFFER_READY resources navigate to the existing custom-plan offer route", async () => {
  const code = await read("../src/shared/components/layout/Topbar.jsx");
  const routes = await read("../src/app/router/routePaths.js");

  assert.match(code, /notification\.resourceType === ["']custom_plan_quote["']/);
  assert.match(code, /notification\.resourceId \?\? notification\.payload\?\.quoteId/);
  assert.match(code, /routePaths\.customPlanOffer\.replace/);
  assert.match(routes, /customPlanOffer:\s*["']\/billing\/custom-offer\/:quoteId["']/);
});

test("notification title/body are localized from backend keys and payload", async () => {
  const code = await read("../src/shared/components/layout/Topbar.jsx");
  const en = await readJson("../src/assets/locales/en.json");
  const ar = await readJson("../src/assets/locales/ar.json");

  assert.match(code, /t\(notification\.titleKey, notification\.payload \?\? \{\}\)/);
  assert.match(code, /t\(notification\.bodyKey, notification\.payload \?\? \{\}\)/);

  assert.equal(
    en.tenantNotifications.customPlanOfferReady.title,
    "Your custom plan offer is ready"
  );
  assert.match(en.tenantNotifications.customPlanOfferReady.body, /\{\{quoteName\}\}/);
  assert.ok(ar.tenantNotifications.customPlanOfferReady.title);
  assert.match(ar.tenantNotifications.customPlanOfferReady.body, /\{\{quoteName\}\}/);
});

test("notification dropdown styling stays scoped to the tenant topbar", async () => {
  const css = await read("../src/styles/business-shell.css");

  assert.match(css, /\.business-topbar__notification-preview\s*\{/);
  assert.match(css, /\.business-topbar__notification-item\.is-unread/);
  assert.match(css, /\.business-topbar__notification-archive/);
  assert.match(css, /\.business-topbar__profile-menu\s*\{/);
});
