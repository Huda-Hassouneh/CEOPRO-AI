import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { inventoryReason } from "../src/features/forecasting/utils/inventoryPresentation.js";
test("all inventory unavailable reasons have matching customer-facing English and Arabic text", () => {
  const messages = ["en", "ar"].map((lang) => JSON.parse(readFileSync(new URL(`../src/assets/locales/${lang}.json`, import.meta.url))));
  assert.deepEqual(Object.keys(messages[0].demandApproved.inventoryEvidence.reasons), Object.keys(messages[1].demandApproved.inventoryEvidence.reasons));
  for (const lang of messages) {
    const t = (key) => key.split('.').reduce((item, part) => item?.[part], lang);
    for (const reason of Object.keys(lang.demandApproved.inventoryEvidence.reasons)) {
      assert.equal(inventoryReason({ reason }, t), lang.demandApproved.inventoryEvidence.reasons[reason]);
      assert.ok(inventoryReason({ reason }, t).length > 15);
    }
    assert.equal(inventoryReason({ reason: "unknown" }, t), lang.demandApproved.empty.recommendationDescription);
  }
});
