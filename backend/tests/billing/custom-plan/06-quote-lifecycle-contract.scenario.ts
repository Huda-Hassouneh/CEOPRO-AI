import test from "node:test";
import assert from "node:assert/strict";
import {
  assertIncludesAll,
  assertMatches,
  readProjectFile,
} from "./_helpers.js";

const configurator = readProjectFile(
  "src/modules/subscription/service/custom-plan-configurator.service.ts",
);
const service = readProjectFile(
  "src/modules/subscription/service/custom-plan.service.ts",
);
const repo = readProjectFile(
  "src/modules/subscription/repo/custom-plan.repo.ts",
);
const plansService = readProjectFile(
  "src/modules/subscription/service/plans.service.ts",
);

test("06.01 automatic quote idempotency binds requestId to configuration and pricing", () => {
  assertIncludesAll(
    configurator,
    [
      "configurationHash(args.input)",
      "pricingFingerprint(args.calculated)",
      "snapshot?.automatic?.configurationHash !== hash",
      "snapshot?.automatic?.pricingFingerprint !== currentPricingFingerprint",
      "ERROR_CODES.RESOURCE_ALREADY_EXISTS",
    ],
    "custom-plan configurator",
  );
});

test("06.02 pricing fingerprint includes vendor and infrastructure pricing evidence", () => {
  assertIncludesAll(
    configurator,
    [
      "vendorRateIds",
      "vendorBreakdown",
      "infrastructureRateIds",
      "infrastructureBreakdown",
      "usageDrivenInfrastructureCost",
      "estimatedInfrastructureCost",
      "targetGrossMargin",
      "fixedPlatformFee",
      "roundingIncrement",
      "fxRate",
    ],
    "pricing fingerprint",
  );
});

test("06.03 manual review triggers cover quota, price, and unverified rates", () => {
  assertIncludesAll(
    configurator,
    [
      "QUOTA_ABOVE_AUTOMATIC_LIMIT:",
      "PRICE_ABOVE_AUTOMATIC_LIMIT",
      "UNVERIFIED_VENDOR_RATE",
    ],
    "manual-review decision",
  );
});

test("06.04 automatic quote is approved with final price; review quote is only calculated", () => {
  assertMatches(
    configurator,
    /status:\s*instant\s*\?\s*"approved"\s*:\s*"calculated"/,
    "automatic/manual status split must remain explicit",
  );
  assertMatches(
    configurator,
    /finalPrice:\s*instant\s*\?\s*c\.pricing!\.recommendedPrice\s*:\s*null/,
    "manual-review quote must not receive a customer-accepted final price automatically",
  );
});

test("06.05 manual-review endpoint refuses configs that are eligible for automatic flow", () => {
  assertIncludesAll(
    configurator,
    [
      "This configuration is eligible for automatic processing and does not require manual review.",
      "calculated.manualReviewReasons!.length === 0",
    ],
    "manual-review endpoint",
  );
});

test("06.06 checkout performs authoritative server-side recalculation", () => {
  assertIncludesAll(
    configurator,
    [
      "Authoritative checkout-time recalculation",
      "calculateConfiguration(previewInput)",
    ],
    "checkout",
  );

  assert.ok(
    !/input\.(price|amount|finalPrice)/.test(
      configurator.slice(
        configurator.indexOf("export async function checkoutCustomPlanConfiguration"),
      ),
    ),
    "checkout must not trust a browser-supplied monetary amount",
  );
});

test("06.07 quote acceptance only allows approved/sent and expires stale offers", () => {
  assertIncludesAll(
    service,
    [
      'const ACCEPTABLE_STATUSES = new Set(["approved", "sent"])',
      "quote.expiresAt.getTime() <= Date.now()",
      'status: "expired"',
      "quote.finalPrice == null",
    ],
    "quote acceptance",
  );
});

test("06.08 already-accepted quote with a created plan is idempotent", () => {
  assertIncludesAll(
    service,
    [
      'quote.status === "accepted" && quote.createdPlan',
      '"Quote was already accepted."',
    ],
    "quote acceptance idempotency",
  );
});

test("06.09 quote-to-plan conversion uses an atomic claim before plan creation", () => {
  assertIncludesAll(
    repo,
    [
      "customPlanQuote.updateMany",
      "createdPlanId: null",
      'status: { in: ["approved", "sent"] }',
      'data: { status: "accepted", acceptedAt: new Date() }',
      "if (claimed.count !== 1)",
    ],
    "quote conversion",
  );
});

test("06.10 accepted plan copies feature limits and operational metadata", () => {
  assertIncludesAll(
    repo,
    [
      "quote.quoteFeatures.map",
      "limit_value: feature.limitValue",
      "metadata: feature.metadata ?? undefined",
    ],
    "quote-to-plan feature persistence",
  );
});

test("06.11 generic plan editor refuses accepted custom plans", () => {
  assertIncludesAll(
    plansService,
    [
      'existingPlan.planType === "custom"',
      "Accepted custom plans are immutable",
      "ERROR_CODES.PLAN_NOT_AVAILABLE",
    ],
    "plan immutability",
  );
});
