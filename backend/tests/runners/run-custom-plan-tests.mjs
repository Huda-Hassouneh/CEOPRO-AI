import { spawnSync } from "node:child_process";

const args = new Set(process.argv.slice(2));
const dbOnly = args.has("--db");
const full = args.has("--full");

const coreGroups = [
  {
    label: "00 - Existing custom-plan source contract",
    command: [process.execPath, "tests/contracts/verify-custom-plan-contract.mjs"],
  },
  { label: "01 - Input / DTO validation", file: "tests/billing/custom-plan/01-input-validation.scenario.ts" },
  { label: "02 - Core pricing", file: "tests/billing/custom-plan/02-pricing-core.scenario.ts" },
  { label: "03 - Competitor monitoring pricing", file: "tests/billing/custom-plan/03-competitor-pricing.scenario.ts" },
  { label: "04 - Infrastructure pricing", file: "tests/billing/custom-plan/04-infrastructure-pricing.scenario.ts" },
  { label: "05 - FX and payment currency", file: "tests/billing/custom-plan/05-rate-and-payment-currency.scenario.ts" },
  { label: "06 - Quote lifecycle", file: "tests/billing/custom-plan/06-quote-lifecycle-contract.scenario.ts" },
  { label: "07 - Tenant security and checkout", file: "tests/billing/custom-plan/07-security-checkout-contract.scenario.ts" },
  { label: "08 - Promo + entitlement contracts", file: "tests/billing/custom-plan/08-promo-entitlements-contract.scenario.ts" },
  { label: "09 - Idempotency + concurrency contracts", file: "tests/billing/custom-plan/09-idempotency-concurrency-contract.scenario.ts" },
  { label: "10 - Schema + migration contracts", file: "tests/billing/custom-plan/10-schema-migration-contract.scenario.ts" },
];

const dbGroup = {
  label: "11 - Disposable database integration smoke",
  file: "tests/billing/custom-plan/11-live-db-smoke.scenario.ts",
};

if ((dbOnly || full) && !process.env.CUSTOM_PLAN_TEST_DATABASE_URL?.trim()) {
  console.error("\nCUSTOM_PLAN_TEST_DATABASE_URL is required for DB tests.");
  console.error("Point it at a disposable database that already has `prisma migrate deploy` applied.");
  console.error("The DB test creates temporary rows and deletes them after the run.\n");
  process.exit(2);
}

const groups = dbOnly ? [dbGroup] : full ? [...coreGroups, dbGroup] : coreGroups;

console.log("\n============================================================");
console.log(" CEOPRO Custom Plan Automated Test Suite");
console.log("============================================================");
console.log(`Mode: ${dbOnly ? "database only" : full ? "full (core + database)" : "core / no external services"}`);
console.log(`Groups: ${groups.length}`);
console.log("============================================================\n");

let passed = 0;
const failures = [];
const startedAt = Date.now();

for (let index = 0; index < groups.length; index += 1) {
  const group = groups[index];
  console.log(`\n[${String(index + 1).padStart(2, "0")}/${String(groups.length).padStart(2, "0")}] ${group.label}`);
  console.log("-".repeat(60));

  const command =
    group.command ??
    [
      process.execPath,
      "--import",
      "tsx",
      "--test",
      "--test-reporter=spec",
      group.file,
    ];

  const [bin, ...binArgs] = command;
  const result = spawnSync(bin, binArgs, {
    cwd: process.cwd(),
    env: process.env,
    stdio: "inherit",
  });

  if (result.status === 0) {
    passed += 1;
    console.log(`\nPASS GROUP: ${group.label}`);
  } else {
    failures.push(group.label);
    console.error(`\nFAIL GROUP: ${group.label}`);
  }
}

const elapsed = ((Date.now() - startedAt) / 1000).toFixed(1);

console.log("\n============================================================");
console.log(" Custom Plan Test Summary");
console.log("============================================================");
console.log(`Passed groups : ${passed}/${groups.length}`);
console.log(`Failed groups : ${failures.length}`);
console.log(`Elapsed       : ${elapsed}s`);

if (failures.length) {
  console.log("\nFailed:");
  for (const failure of failures) console.log(`  - ${failure}`);
  console.log("\nResult: FAILED. Fix the failed contract/scenario before release.");
  process.exit(1);
}

console.log("\nResult: PASSED.");
console.log("============================================================\n");
