import { spawnSync } from "node:child_process";

const dbUrl = (
  process.env.SUBSCRIPTION_TEST_DATABASE_URL ||
  process.env.CUSTOM_PLAN_TEST_DATABASE_URL ||
  ""
).trim();
const stripeKey = (process.env.STRIPE_SECRET_KEY || "").trim();

if (!dbUrl) {
  console.error("\nSUBSCRIPTION_TEST_DATABASE_URL or CUSTOM_PLAN_TEST_DATABASE_URL is required.");
  console.error("Use the same disposable migrated PostgreSQL database used for the custom-plan DB tests.\n");
  process.exit(2);
}
if (!/test/i.test(dbUrl)) {
  console.error("\nREFUSED: lifecycle tests only run when the database URL contains 'test'.");
  console.error("Point them at a disposable test database, never a development/production database.\n");
  process.exit(2);
}
if (!stripeKey) {
  console.error("\nSTRIPE_SECRET_KEY is required for lifecycle tests.\n");
  process.exit(2);
}
if (!stripeKey.startsWith("sk_test_")) {
  console.error("\nREFUSED: lifecycle tests only run with an sk_test_ Stripe key. Never use a live key.\n");
  process.exit(2);
}

process.env.DATABASE_URL = dbUrl;
process.env.SUBSCRIPTION_TEST_DATABASE_URL ||= dbUrl;
process.env.SUCCESS_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-success";
process.env.FAILED_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-cancelled";
process.env.PROMO_FIXED_AMOUNT_CURRENCY ||= "USD";
process.env.STRIPE_USE_TEST_CLOCK = "false";

const groups = [
  ["20 - Status + access contract", "tests/billing/subscription-lifecycle/20-status-access-contract.scenario.ts"],
  ["21 - Billing-cycle reset", "tests/billing/subscription-lifecycle/21-billing-cycle-reset.scenario.ts"],
  ["22 - Trial lifecycle", "tests/billing/subscription-lifecycle/22-trial-lifecycle.scenario.ts"],
  ["23 - Cancellation lifecycle", "tests/billing/subscription-lifecycle/23-cancellation-lifecycle.scenario.ts"],
  ["24 - Plan-change lifecycle", "tests/billing/subscription-lifecycle/24-plan-change-lifecycle.scenario.ts"],
  ["25 - Webhook reliability", "tests/billing/subscription-lifecycle/25-webhook-reliability.scenario.ts"],
  ["26 - Payment recovery", "tests/billing/subscription-lifecycle/26-payment-recovery.scenario.ts"],
];

console.log("\n============================================================");
console.log(" CEOPRO Subscription Lifecycle Stripe TEST Suite");
console.log("============================================================");
console.log("Safety: disposable TEST DB + sk_test_ key required");
console.log("Backend server: NOT required");
console.log("Stripe CLI listener: NOT required (stop it to avoid double-processing)");
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
console.log(" Subscription Lifecycle Summary");
console.log("============================================================");
console.log(`Passed groups : ${passed}/${groups.length}`);
console.log(`Failed groups : ${failed.length}`);
console.log(`Elapsed       : ${elapsed}s`);

if (failed.length) {
  console.log("\nFailed:");
  for (const label of failed) console.log(`  - ${label}`);
  console.log("\nResult: FAILED. Send the full output; fix implementation or test assumptions before release.");
  process.exit(1);
}

console.log("\nResult: PASSED.");
console.log("============================================================\n");
