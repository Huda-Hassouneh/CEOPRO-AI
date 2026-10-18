// Runs a browser check in English desktop, Arabic mobile and dark mode:
// the screen smoke test by default, or `a11y` for the accessibility audit.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const suite = process.argv[2] === 'a11y' ? 'a11y' : 'smoke';
const script = fileURLToPath(new URL(`./${suite}.mjs`, import.meta.url));
const runs = [{}, { E2E_LOCALE: 'ar', E2E_WIDTH: '390' }, { E2E_THEME: 'dark', E2E_WIDTH: '390' }];
let failed = 0;
for (const env of runs) {
  const result = spawnSync(process.execPath, [script], { stdio: 'inherit', env: { ...process.env, ...env } });
  if (result.status !== 0) failed += 1;
}
process.exit(failed ? 1 : 0);
