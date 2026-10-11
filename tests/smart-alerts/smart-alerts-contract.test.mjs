import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("system_alerts is a lifetime boolean catalog feature", async () => {
  const catalog = await read("../../src/modules/features/catalog.ts");
  const feature = catalog.match(/\{\s*code: "system_alerts"[\s\S]*?\n  \},/);
  assert.ok(feature, "canonical Smart Alerts feature is present");
  assert.match(feature[0], /type: FeatureType\.boolean/);
  assert.match(feature[0], /resetCycle: ResetCycle\.lifetime/);
});

test("Starter, Growth, and Enterprise production plans do not grant Smart Alerts", async () => {
  const manifest = await read("../../src/config/production-plans.ts");
  assert.match(manifest, /code: "starter"/);
  assert.match(manifest, /code: "growth"/);
  assert.match(manifest, /code: "enterprise"/);
  assert.doesNotMatch(manifest, /booleanFeature\("system_alerts"\)/);
});

test("AI price change uses a signed percent and guards zero baseline", async () => {
  const repository = await read("../../../ai/src/market_scraper/market_repository.py");
  assert.match(repository, /if old_price == 0:\s*return/);
  assert.match(repository, /\(new_price - old_price\) \/ old_price \* 100/);
});

test("AI queries active price-change rules within tenant and competitor scope", async () => {
  const repository = await read("../../../ai/src/market_scraper/market_repository.py");
  const evaluator = repository.match(/def _trigger_price_alerts[\s\S]*?\n\ndef save_market_record/);
  assert.ok(evaluator);
  assert.match(evaluator[0], /tenant_id = %s/);
  assert.match(evaluator[0], /global_competitor_id = %s/);
  assert.match(evaluator[0], /metric = 'PRICE_CHANGE_PERCENT'/);
  assert.match(evaluator[0], /is_active = TRUE/);
});

test("market price rows reject negative amounts and malformed ISO currency", async () => {
  const sql = await read("../../../ai/src/infrastructure/database/Final_schema.sql");
  assert.match(sql, /scraped_price NUMERIC\(12, 4\) NOT NULL CHECK \(scraped_price >= 0\)/);
  assert.match(sql, /currency VARCHAR\(3\) NOT NULL CHECK \(currency ~ '\^\[A-Z\]\{3\}\$'\)/);
});

test("Smart Alerts schema is tenant-scoped and records acknowledgement separately from inbox receipts", async () => {
  const schema = await read("../../prisma/schema.prisma");
  const alertEvent = schema.match(/model market_alert_events \{[\s\S]*?\n\}/);
  assert.ok(alertEvent);
  assert.match(alertEvent[0], /tenant_id\s+String/);
  assert.match(alertEvent[0], /acknowledged_at\s+DateTime\?/);
  const receipt = schema.match(/model TenantNotificationReceipt \{[\s\S]*?\n\}/);
  assert.ok(receipt);
  assert.match(receipt[0], /readAt\s+DateTime\?/);
  assert.match(receipt[0], /archivedAt\s+DateTime\?/);
  assert.doesNotMatch(receipt[0], /acknowledged|resolved/i);
});

test("the tenant notification event contract has no Smart Alerts producer yet", async () => {
  const types = await read("../../src/modules/tenant-notifications/tenant-notification.types.ts");
  const definition = await read("../../src/modules/tenant-notifications/tenant-notification.definition.ts");
  assert.match(types, /CUSTOM_PLAN_OFFER_READY/);
  assert.doesNotMatch(types, /MARKET_ALERT|SMART_ALERT/);
  assert.doesNotMatch(definition, /MARKET_ALERT|SMART_ALERT/);
});

test("essential custom-plan offer notifications remain independent of Smart Alerts entitlement", async () => {
  const definition = await read("../../src/modules/tenant-notifications/tenant-notification.definition.ts");
  const producer = await read("../../src/modules/tenant-notifications/tenant-notification.producer.ts");
  assert.match(definition, /CUSTOM_PLAN_OFFER_READY/);
  assert.match(definition, /requiredPermissions:\s*\["manage_billing"\]/);
  assert.match(producer, /customPlanOfferReady/);
  assert.doesNotMatch(definition + producer, /requireEntitlement\(["']system_alerts/);
});

test("outbox, final notification, and recipient receipts have persistent dedupe and tenant ownership", async () => {
  const schema = await read("../../prisma/schema.prisma");
  const outbox = schema.match(/model TenantNotificationOutbox \{[\s\S]*?\n\}/);
  const notification = schema.match(/model TenantNotification \{[\s\S]*?\n\}/);
  const receipt = schema.match(/model TenantNotificationReceipt \{[\s\S]*?\n\}/);
  assert.match(outbox?.[0] || "", /@@unique\(\[tenantId, dedupeKey\]/);
  assert.match(notification?.[0] || "", /@@unique\(\[tenantId, dedupeKey\]/);
  assert.match(receipt?.[0] || "", /@@id\(\[notificationId, recipientUserId\]\)/);
});

test("the shared tenant inbox is authenticated and receipt actions are recipient-scoped", async () => {
  const route = await read("../../src/modules/tenant-notifications/route/tenant-notification.route.ts");
  const repo = await read("../../src/modules/tenant-notifications/repo/tenant-notification.repo.ts");
  assert.match(route, /router\.use\(authenticateUser, requireTenant\)/);
  assert.match(repo, /recipientUserId: args\.recipientUserId/);
  assert.match(repo, /setRlsContext\(tx, args\.tenantId, args\.recipientUserId\)/);
  assert.match(repo, /notificationId: args\.notificationId/);
});

test("worker claims due rows conditionally and uses bounded retry policy", async () => {
  const repo = await read("../../src/modules/tenant-notifications/repo/tenant-notification.repo.ts");
  const worker = await read("../../src/workers/tenant-notification.worker.ts");
  assert.match(repo, /where:\s*\{[\s\S]*?status:\s*\{\s*in: \["pending", "processing"\]/);
  assert.match(repo, /nextAttemptAt:\s*\{\s*lte: now/);
  assert.match(repo, /if \(result\.count !== 1\)/);
  assert.match(worker, /MAX_ATTEMPTS = 5/);
  assert.match(worker, /BASE_RETRY_MS = 30_000/);
  assert.match(worker, /MAX_RETRY_MS = 15 \* 60 \* 1000/);
});

test("notification delivery and outbox completion commit in one worker transaction", async () => {
  const dispatcher = await read("../../src/modules/tenant-notifications/tenant-notification.dispatcher.ts");
  assert.match(dispatcher, /notificationWorkerPrisma\.\$transaction/);
  assert.match(dispatcher, /createNotification\(tx/);
  assert.match(dispatcher, /createReceipts\(tx/);
  assert.match(dispatcher, /markOutboxDelivered\(\s*tx\s*,/);
});

test("tenant notification routes expose read/archive but no Smart Alert rule or resolution API", async () => {
  const route = await read("../../src/modules/tenant-notifications/route/tenant-notification.route.ts");
  assert.match(route, /\/:id\/read/);
  assert.match(route, /\/:id\/archive/);
  assert.doesNotMatch(route, /market-alert|smart-alert|acknowledge|resolve/i);
});

test("notification preferences are currently presented as unavailable rather than operational", async () => {
  const component = await read("../../../frontend/src/features/settings/components/NotificationSettings.jsx");
  assert.match(component, /settings\.notifications\.unavailableTitle/);
  assert.match(component, /settings\.notifications\.unavailableDescription/);
});

test("customer bell displays only records returned by authenticated tenant inbox APIs", async () => {
  const topbar = await read("../../../frontend/src/shared/components/layout/Topbar.jsx");
  const hook = await read("../../../frontend/src/features/notifications/hooks/useTenantNotifications.js");
  assert.match(topbar, /notifications\.map\(\(notification\)/);
  assert.match(topbar, /notification\.titleKey/);
  assert.match(topbar, /notification\.bodyKey/);
  assert.match(hook, /notificationsApi\.list/);
  assert.match(hook, /const enabled = !UI_TESTING_MODE && Boolean\(tenantId/);
});
