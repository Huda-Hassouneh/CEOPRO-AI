import { spawnSync } from 'node:child_process';

const groups = [
  ['34', 'Production catalog source', 'tests/frontend-billing/34-production-catalog-source.scenario.mjs'],
  ['35', 'Tier names + i18n', 'tests/frontend-billing/35-tier-copy-i18n.scenario.mjs'],
  ['36', 'Billing periods + currency', 'tests/frontend-billing/36-billing-period-currency.scenario.mjs'],
  ['37', 'Custom Plan preserved', 'tests/frontend-billing/37-custom-plan-preserved.scenario.mjs'],
  ['38', 'Checkout authority', 'tests/frontend-billing/38-checkout-authority.scenario.mjs'],
  ['39', 'Onboarding success path', 'tests/frontend-billing/39-onboarding-success.scenario.mjs'],
  ['40', 'Production UI guard', 'tests/frontend-billing/40-production-ui-guard.scenario.mjs'],
  ['41', 'Compact plan-card UX', 'tests/frontend-billing/41-plan-card-ux.scenario.mjs'],
];

console.log('\n============================================================');
console.log(' CEOPRO Frontend Billing Production Verification Suite');
console.log('============================================================');
console.log('Backend server: NOT required');
console.log('Stripe CLI: NOT required');
console.log(`Groups: ${groups.length}`);
console.log('============================================================\n');

const failed = [];
const started = Date.now();

for (let index = 0; index < groups.length; index += 1) {
  const [id, name, file] = groups[index];
  console.log(`[${String(index + 1).padStart(2, '0')}/${String(groups.length).padStart(2, '0')}] ${id} - ${name}`);
  console.log('------------------------------------------------------------');

  const result = spawnSync(process.execPath, ['--test', '--test-reporter=spec', file], {
    cwd: process.cwd(),
    env: process.env,
    stdio: 'inherit',
  });

  if (result.status === 0) {
    console.log(`\nPASS GROUP: ${id} - ${name}\n`);
  } else {
    failed.push(`${id} - ${name}`);
    console.log(`\nFAIL GROUP: ${id} - ${name}\n`);
  }
}

const elapsed = ((Date.now() - started) / 1000).toFixed(1);
console.log('============================================================');
console.log(' Frontend Billing Verification Summary');
console.log('============================================================');
console.log(`Passed groups : ${groups.length - failed.length}/${groups.length}`);
console.log(`Failed groups : ${failed.length}`);
console.log(`Elapsed       : ${elapsed}s`);
if (failed.length) {
  console.log('\nFailed:');
  failed.forEach((name) => console.log(`  - ${name}`));
  console.log('\nResult: FAILED. These failures indicate frontend production-alignment gaps.');
  process.exit(1);
}
console.log('\nResult: PASSED.');
console.log('============================================================');
