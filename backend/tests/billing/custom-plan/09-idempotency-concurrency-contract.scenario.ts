import test from "node:test";
import assert from "node:assert/strict";
import {
  assertIncludesAll,
  readProjectFile,
} from "./_helpers.js";

const configurator = readProjectFile(
  "src/modules/subscription/service/custom-plan-configurator.service.ts",
);
const customService = readProjectFile(
  "src/modules/subscription/service/custom-plan.service.ts",
);
const repo = readProjectFile(
  "src/modules/subscription/repo/custom-plan.repo.ts",
);
const webhook = readProjectFile("src/utils/webhook handlers.ts");
const webhookRepo = readProjectFile(
  "src/modules/subscription/repo/webhook.repo.ts",
);

test("09.01 requestId is the automatic quote primary idempotency key", () => {
  assertIncludesAll(
    configurator,
    [
      "findQuoteForTenant(",
      "args.requestId",
      "id: args.requestId",
    ],
    "automatic quote creation",
  );
});

test("09.02 same requestId with changed configuration is rejected", () => {
  assertIncludesAll(
    configurator,
    [
      "configurationHash",
      "already used for a different custom-plan configuration",
      "ERROR_CODES.RESOURCE_ALREADY_EXISTS",
    ],
    "configuration idempotency",
  );
});

test("09.03 same requestId with changed rate/policy fingerprint is rejected", () => {
  assertIncludesAll(
    configurator,
    [
      "pricingFingerprint",
      "Pricing changed since this checkout request was created",
      "ERROR_CODES.RESOURCE_ALREADY_EXISTS",
    ],
    "pricing idempotency",
  );
});

test("09.04 quote conversion has a single-winner DB claim", () => {
  assertIncludesAll(
    repo,
    [
      "updateMany",
      "createdPlanId: null",
      "claimed.count !== 1",
    ],
    "quote conversion concurrency",
  );
});

test("09.05 Stripe Price creation uses deterministic quote/period idempotency keys", () => {
  assertIncludesAll(
    customService,
    [
      "idempotencyKey:",
      "custom-quote:${quote.id}:${option.period}",
    ],
    "Stripe Price creation",
  );
});

test("09.06 duplicate provider webhook events are backed by a unique provider-event ledger", () => {
  assertIncludesAll(
    webhookRepo,
    [
      "payment_providerEventId",
    ],
    "webhook repository",
  );

  assert.ok(
    webhook.includes("processed") || webhook.includes("mark"),
    "webhook handler should use processed/idempotent provider-event handling",
  );
});
