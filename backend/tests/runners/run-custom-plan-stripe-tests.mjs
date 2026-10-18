import { spawnSync } from "node:child_process";

const dbUrl = process.env.CUSTOM_PLAN_TEST_DATABASE_URL?.trim();
const stripeKey = process.env.STRIPE_SECRET_KEY?.trim();

if (!dbUrl) {
  console.error("\nCUSTOM_PLAN_TEST_DATABASE_URL is required.");
  console.error("Use the disposable migrated database from test:custom-plan:db.\n");
  process.exit(2);
}
if (!stripeKey) {
  console.error("\nSTRIPE_SECRET_KEY is required for Stripe E2E tests.\n");
  process.exit(2);
}
if (!stripeKey.startsWith("sk_test_")) {
  console.error("\nREFUSED: Stripe E2E tests only run with an sk_test_ key. Never use a live Stripe key.\n");
  process.exit(2);
}

process.env.DATABASE_URL = dbUrl;
process.env.STRIPE_E2E_WEBHOOK_SECRET ||= "whsec_ceopro_local_e2e_secret";
process.env.STRIPE_SECRET_WEBHOOK ||= process.env.STRIPE_E2E_WEBHOOK_SECRET;
process.env.SUCCESS_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-success";
process.env.FAILED_SUBSCRIPTION_URL ||= "http://127.0.0.1:5173/payment-cancelled";
process.env.PROMO_FIXED_AMOUNT_CURRENCY ||= "USD";

const groups = [
  ["12 - Stripe checkout provider object", "tests/billing/custom-plan-stripe/12-stripe-checkout-provider.scenario.ts"],
  ["13 - Webhook signature + idempotency", "tests/billing/custom-plan-stripe/13-webhook-signature-idempotency.scenario.ts"],
  ["14 - Successful subscription synchronization", "tests/billing/custom-plan-stripe/14-successful-subscription-sync.scenario.ts"],
  ["15 - Payment failure + recovery", "tests/billing/custom-plan-stripe/15-payment-failure-recovery.scenario.ts"],
  ["16 - Test Clock renewal + allocation reset", "tests/billing/custom-plan-stripe/16-test-clock-renewal.scenario.ts"],
  ["17 - Promo provider amount", "tests/billing/custom-plan-stripe/17-promo-provider-amount.scenario.ts"],
  ["18 - Automatic custom-plan golden path", "tests/billing/custom-plan-stripe/18-automatic-golden-path.scenario.ts"],
  ["19 - Manual-review golden path", "tests/billing/custom-plan-stripe/19-manual-review-golden-path.scenario.ts"],
];

console.log("\n============================================================");
console.log(" CEOPRO Custom Plan Stripe TEST-Mode E2E Suite");
console.log("============================================================");
console.log("Safety: sk_test_ key required; live keys are refused");
console.log(`Groups: ${groups.length}`);
console.log("DB: disposable CUSTOM_PLAN_TEST_DATABASE_URL");
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
console.log(" Stripe E2E Summary");
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
