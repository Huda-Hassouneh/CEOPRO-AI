import test from "node:test";
import assert from "node:assert/strict";
import {
  assertIncludesAll,
  readProjectFile,
} from "./_helpers.js";

const schema = readProjectFile("prisma/schema.prisma");
const baseline = readProjectFile(
  "prisma/migrations/20260800000000_baseline/migration.sql",
);
const infraMigration = readProjectFile(
  "prisma/migrations/20260929210000_add_infrastructure_rates/migration.sql",
);
const featureMetadataMigration = readProjectFile(
  "prisma/migrations/20260929190000_add_plan_feature_configuration/migration.sql",
);

test("10.01 schema distinguishes standard and tenant-private custom plans", () => {
  assertIncludesAll(
    schema,
    [
      "enum PlanType",
      "standard",
      "custom",
      "planType",
      "tenantId",
    ],
    "Prisma schema",
  );
});

test("10.02 quote schema has tenant, pricing evidence, final price and accepted plan link", () => {
  assertIncludesAll(
    schema,
    [
      "model CustomPlanQuote",
      "tenantId",
      "pricingInputs",
      "pricingSnapshot",
      "minimumSafePrice",
      "finalPrice",
      "createdPlanId",
      "acceptedAt",
    ],
    "CustomPlanQuote",
  );
});

test("10.03 a quote cannot contain the same feature twice", () => {
  assertIncludesAll(
    baseline,
    [
      "custom_plan_quote_features_quote_id_feature_id_key",
      "UNIQUE (quote_id, feature_id)",
    ],
    "baseline migration",
  );
});

test("10.04 one created plan can belong to only one quote", () => {
  assertIncludesAll(
    baseline,
    [
      "custom_plan_quotes_created_plan_id_key UNIQUE (created_plan_id)",
    ],
    "baseline migration",
  );
});

test("10.05 infrastructure rates are a separate versioned cost domain with DB checks", () => {
  assertIncludesAll(
    infraMigration,
    [
      "CREATE TABLE infrastructure_rates",
      "infrastructure_rates_unit_cost_nonnegative_chk",
      "infrastructure_rates_billing_units_positive_chk",
      "infrastructure_rates_operational_multiplier_positive_chk",
      "infrastructure_rates_variability_reserve_min_chk",
      "infrastructure_rates_effective_window_chk",
      "infrastructure_rates_currency_chk",
    ],
    "infrastructure migration",
  );
});

test("10.06 feature-specific operational configuration survives quote acceptance", () => {
  assertIncludesAll(
    featureMetadataMigration,
    ['ALTER TABLE "plan_features"', 'ADD COLUMN "metadata" JSONB'],
    "plan feature metadata migration",
  );
});

test("10.07 custom plan quote status machine contains terminal accepted/rejected/expired states", () => {
  assertIncludesAll(
    schema,
    [
      "enum CustomPlanQuoteStatus",
      "draft",
      "calculated",
      "approved",
      "sent",
      "accepted",
      "rejected",
      "expired",
    ],
    "quote status enum",
  );
});

test("10.08 webhook event ledger has a unique payment-provider event id", () => {
  assertIncludesAll(
    baseline,
    [
      "payment_provider_webhook_events_payment_provider_event_id_key",
      "UNIQUE (payment_provider_event_id)",
    ],
    "webhook ledger migration",
  );
});
