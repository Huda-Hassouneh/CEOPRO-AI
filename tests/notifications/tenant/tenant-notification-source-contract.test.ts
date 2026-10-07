import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

async function source(path: string) {
  return readFile(new URL(path, import.meta.url), "utf8");
}

test("sending a custom plan quote and enqueueing its notification share one transaction", async () => {
  const code = await source(
    "../../../src/modules/subscription/service/custom-plan.service.ts"
  );

  const functionStart = code.indexOf("export async function sendCustomPlanQuote");
  const transactionStart = code.indexOf("await prisma.$transaction", functionStart);
  const quoteWrite = code.indexOf("tx.customPlanQuote.updateMany", transactionStart);
  const notificationWrite = code.indexOf(
    "tenantNotificationProducer.customPlanOfferReady(tx",
    transactionStart
  );

  assert.ok(functionStart >= 0, "sendCustomPlanQuote must exist");
  assert.ok(transactionStart > functionStart, "send must use one DB transaction");
  assert.ok(quoteWrite > transactionStart, "quote status update must be transactional");
  assert.ok(
    notificationWrite > quoteWrite,
    "outbox insert must happen in the same transaction after claiming the quote"
  );
});

test("tenant notification HTTP routes expose list, unread, read-all, read and archive", async () => {
  const code = await source(
    "../../../src/modules/tenant-notifications/route/tenant-notification.route.ts"
  );

  assert.match(code, /router\.use\(authenticateUser, requireTenant\)/);
  assert.match(code, /router\.get\("\/"/);
  assert.match(code, /router\.get\("\/unread-count"/);
  assert.match(code, /router\.post\("\/read-all"/);
  assert.match(code, /router\.post\("\/:id\/read"/);
  assert.match(code, /router\.post\("\/:id\/archive"/);
});

test("tenant notification API is mounted at /notifications", async () => {
  const code = await source("../../../src/app.ts");

  assert.match(
    code,
    /app\.use\("\/notifications", tenantNotificationRouter\)/
  );
});

test("dispatcher and worker persistence use the dedicated notification worker Prisma client", async () => {
  const dispatcher = await source(
    "../../../src/modules/tenant-notifications/tenant-notification.dispatcher.ts"
  );
  const repo = await source(
    "../../../src/modules/tenant-notifications/repo/tenant-notification.repo.ts"
  );

  assert.match(dispatcher, /notificationWorkerPrisma\.\$transaction/);
  assert.match(repo, /notificationWorkerPrisma\.tenantNotificationOutbox/);
});

test("CUSTOM_PLAN_OFFER_READY recipients are selected by tenant manage_billing permission", async () => {
  const definition = await source(
    "../../../src/modules/tenant-notifications/tenant-notification.definition.ts"
  );
  const repo = await source(
    "../../../src/modules/tenant-notifications/repo/tenant-notification.repo.ts"
  );

  assert.match(definition, /requiredPermissions:\s*\["manage_billing"\]/);
  assert.match(repo, /permissions\.all === true/);
  assert.match(repo, /permissions\[permission\] === true/);
});

test("active customer custom-plan acceptance route uses manage_billing", async () => {
  const subscriptionIndex = await source(
    "../../../src/modules/subscription/index.ts"
  );
  const route = await source(
    "../../../src/modules/subscription/route/custom-plan.route.ts"
  );

  assert.match(
    subscriptionIndex,
    /import customPlanRoutes from "\.\/route\/custom-plan\.route\.js"/
  );
  assert.match(
    route,
    /"\/quotes\/:id\/accept"[\s\S]*requirePermission\("manage_billing"\)/
  );
});
