import { spawnSync } from "node:child_process";

const dbUrl = (
  process.env.PRODUCTION_PLAN_TEST_DATABASE_URL ||
  process.env.SUBSCRIPTION_TEST_DATABASE_URL ||
  process.env.CUSTOM_PLAN_TEST_DATABASE_URL ||
  ""
).trim();
const stripeKey = (process.env.STRIPE_SECRET_KEY || "").trim();

if (!dbUrl) {
  console.error("\nPRODUCTION_PLAN_TEST_DATABASE_URL (or the existing disposable test DB variable) is required.\n");
  process.exit(2);
}
if (!/test/i.test(dbUrl)) {
  console.error("\nREFUSED: production-plan verification only runs when the database URL contains 'test'.");
  console.error("Use a disposable migrated database, never development or production.\n");
  process.exit(2);
}
if (!stripeKey) {
  console.error("\nSTRIPE_SECRET_KEY is required.\n");
  process.exit(2);
}
if (!stripeKey.startsWith("sk_test_")) {
  console.error("\nREFUSED: production-plan verification only runs with an sk_test_ Stripe key.\n");
  process.exit(2);
}

process.env.DATABASE_URL = dbUrl;
process.env.PRODUCTION_PLAN_TEST_DATABASE_URL ||= dbUrl;
process.env.SUCCESS_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-success";
process.env.FAILED_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-cancelled";
process.env.PROMO_FIXED_AMOUNT_CURRENCY ||= "USD";
process.env.STRIPE_USE_TEST_CLOCK = "false";

const groups = [
  ["27 - Production catalog boundary", "tests/billing/production-plans/27-catalog-boundary.scenario.ts"],
  ["28 - Stripe bootstrap idempotency", "tests/billing/production-plans/28-stripe-bootstrap-idempotency.scenario.ts"],
  ["29 - Standard-plan pricing + mappings", "tests/billing/production-plans/29-standard-plan-pricing.scenario.ts"],
  ["30 - Public/managed catalog visibility", "tests/billing/production-plans/30-catalog-visibility.scenario.ts"],
  ["31 - Standard-plan checkout", "tests/billing/production-plans/31-standard-checkout.scenario.ts"],
  ["32 - Subscription + entitlements", "tests/billing/production-plans/32-subscription-entitlements.scenario.ts"],
  ["33 - Production bootstrap safety", "tests/billing/production-plans/33-production-bootstrap-safety.scenario.ts"],
];

console.log("\n============================================================");
console.log(" CEOPRO Production Plan / Bootstrap Verification Suite");
console.log("============================================================");
console.log("Safety: disposable TEST DB + sk_test_ Stripe key required");
console.log("Backend server: NOT required");
console.log("Stripe CLI listener: NOT required");
console.log("Important: test fixtures are production-shaped; they are NOT your final real catalog");
console.log(`Groups: ${groups.length}`);
console.log("============================================================\n");

let passed = 0;
const failed = [];
const startedAt = Date.now();

for (let i = 0; i < groups.length; i += 1) {
  const [label, file] = groups[i];
  console.log(`\n[${String(i + 1).padStart(2, "0")}/${String(groups.length).padStart(2, "0")}] ${label}`);
  console.log("-".repeat(60));
  const result = spawnSync(
    process.execPath,
    ["--import", "tsx", "--test", "--test-reporter=spec", file],
    { cwd: process.cwd(), env: process.env, stdio: "inherit" },
  );

  if (result.status === 0) {
    passed += 1;
    console.log(`\nPASS GROUP: ${label}`);
  } else {
    failed.push(label);
    console.error(`\nFAIL GROUP: ${label}`);
  }
}

const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);
console.log("\n============================================================");
console.log(" Production Plan Verification Summary");
console.log("============================================================");
console.log(`Passed groups : ${passed}/${groups.length}`);
console.log(`Failed groups : ${failed.length}`);
console.log(`Elapsed       : ${elapsed}s`);

if (failed.length) {
  console.log("\nFailed:");
  for (const label of failed) console.log(`  - ${label}`);
  console.log("\nResult: FAILED. A failure may be a real release gap (especially group 33), not necessarily a broken test.");
  process.exit(1);
}

console.log("\nResult: PASSED.");
console.log("============================================================\n");
