import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const page = read("../src/features/data-connections/pages/ConnectDataPage.jsx");
const api = read("../src/features/data-connections/api/dataConnectionsApi.js");
const router = read("../src/app/router/index.jsx");
const en = JSON.parse(read("../src/assets/locales/en.json"));
const ar = JSON.parse(read("../src/assets/locales/ar.json"));

test("connected-source page shows used, remaining, and over-limit capacity", () => {
  assert.match(page, /sourceCapacity\?\.currentUsage/);
  assert.match(page, /sourceCapacity\?\.remaining/);
  assert.match(page, /sourceCapacity\?\.isOverLimit/);
  assert.match(page, /sourceCapacity\?\.included === false/);
});

test("persistent registrations are entitlement-gated while manual uploads bypass source-slot gating", () => {
  const addModal = page.slice(page.indexOf("isOpen={addOpen}"));
  const outerGateClose = addModal.indexOf("</FeatureGate>");
  const documentOption = addModal.indexOf('includes("documents")');
  assert.ok(outerGateClose >= 0 && documentOption > outerGateClose);
  assert.match(addModal, /featureCode="data_integration"/);
  assert.match(addModal, /featureCode="connected_data_sources"/);
  const route = router.match(/path: routePaths\.connectData,[\s\S]*?\n  \},/)?.[0] ?? "";
  assert.doesNotMatch(route, /FeatureRouteGuard[^>]*connected_data_sources/);
});

test("disconnect uses the authenticated API and confirms before clearing credentials", () => {
  assert.match(api, /httpClient\.delete\([\s\S]*?\/connection/);
  assert.match(page, /setDisconnectSource\(source\)/);
  assert.match(page, /confirmDisconnect/);
  assert.match(page, /result\?\.connectionStatus !== "disconnected"/);
});

test("English and Arabic copy explains capacity, downgrade recovery, and credential removal", () => {
  for (const locale of [en, ar]) {
    assert.ok(locale.connectData.connected.remaining);
    assert.ok(locale.connectData.connected.overLimit);
    assert.ok(locale.connectData.connected.integrationUnavailable);
    assert.ok(locale.connectData.connected.disconnectedHelp);
    assert.ok(locale.connectData.disconnect.description);
    assert.ok(locale.connectData.feedback.disconnected);
  }
});
