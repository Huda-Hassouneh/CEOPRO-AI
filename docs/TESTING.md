# Testing KEEL

Run commands from the repository root after `setup`. Choose the smallest suite
that verifies the changed business outcome. External provider acceptance is
separate from offline fixtures and local runtime readiness.

## Choose a suite

| Command | What it runs | Requirements / scope |
|---|---|---|
| `.\dev.ps1 test` | Developer-tooling unit tests | Installed Python dependencies; no services/providers |
| `.\dev.ps1 test --suite frontend` | Frontend Node tests, ESLint and Vite production build | npm dependencies; no paid providers |
| `.\dev.ps1 test --suite database` | Fresh/repeat migrations and native RLS tests | Docker and a fully migrated checkout DB; creates a separate retained test DB |
| `.\dev.ps1 test --suite backend` | Existing backend CI selection on isolated infrastructure | Docker; full model-library dependencies for broad collection; no live-provider opt-ins by default |
| `.\dev.ps1 test --suite browser` | Public English/Arabic login/signup rendering, RTL, proxy/plans and unauthorized platform denial | Running checkout, installed Chrome/Chromium; no account creation or provider generation |
| `.\dev.ps1 test --suite browser-ci` | Authenticated browser CI on disposable DB/services | Docker, model libraries, Chrome/Chromium; synthetic accounts and business mutations |
| `.\dev.ps1 test --suite a11y` | Browser accessibility checks in the isolated CI environment | Same isolation and browser prerequisites |
| `.\dev.ps1 test --suite audit` | `pip check` and unsuppressed dependency audit | Installed dependencies; advisory-service network access; not a feature test |

All root suites first run tooling tests. Bash uses the same command arguments
through `bash dev.sh`; current execution evidence is Windows-specific.
`browser-ci` is not the same scope as the public `browser` smoke.

## Focused backend changes

Prefer the supported isolated runner rather than setting a test DSN to the
development database. For example, approved pricing and accounting changes:

```powershell
.\dev.ps1 test --suite backend --pytest-args src/ai/tests/test_provider_pricing_bootstrap_integration_db.py src/ai/tests/test_credits_integration_db.py src/ai/tests/test_migration_filenames.py -q
```

Or one verified-email, local onboarding flow:

```powershell
.\dev.ps1 test --suite backend --pytest-args src/ai/tests/test_ci_smoke_onboarding_integration_db.py -q
```

Arguments after `--pytest-args` go to pytest. The runner creates a new
`keel_billing_test_dev...` DB, applies migrations twice, verifies restricted
password login/FORCE RLS and supplies test-only Redis, MinIO and Mailpit.
It excludes configured provider credentials and Test Clock opt-ins from the
normal checkout. Test APIs use restricted credentials; explicit migration/native
fixture setup uses the separate test installation authority.

Results are private in `.dev/evidence/tests/<run-id>/`: `run.json`,
`migrations.log`, `backend.log` and JUnit XML. Read the recorded selection,
counts, skips and exit status. A passing small selection is not the full suite.
Some native tests retain additional disposable DBs, named in captured output.

Broad collection imports optional ML packages even when tests mock inference.
Run `down`, `setup --models`, then the required suite if those packages are
needed; this installs libraries, not proof of working models/providers.
Do not use a personal shared venv as the fresh-clone dependency solution.

For an entirely offline module, the [debugging environment example](LOCAL_DEVELOPMENT.md#debugging-and-individual-processes)
can run pytest directly with a validated local environment. Do not point a
mutating/native DB module at the normal customer database by copying that example.

## Frontend and browser changes

`frontend/package.json` is the source for `npm test`, `npm run lint`,
`npm run build`, `npm run test:browser` and `npm run test:a11y`.
Root commands provide the appropriate environment and isolation. Direct browser
scripts require their documented runtime URLs and identities; some create
quotes or business data, so inspect the script before execution.

Check English desktop, Arabic narrow-screen RTL, loading/error/empty states,
tenant denial and actual persisted results. Use screenshots as supporting
evidence; rendering alone does not verify totals, grounding or permissions.
`CHROMIUM_PATH` in private `.dev/integrations.env` can select an installed browser.

## Workers and asynchronous outcomes

Find the owning worker in [Workers](WORKERS.md) and its tests in
`backend/src/ai/tests/` or `backend/src/market_scraper/tests/`. Unit-test payload,
retry and failure behavior first. Then submit a disposable job using supported
APIs and verify completion, persisted evidence, retries and accounting. A 202,
worker log or heartbeat is not a completed forecast/image/sync result.

## Billing and real external providers

Native billing tests under `backend/tests/billing/` exercise authorization,
catalogs, trials, idempotency and financial records on synthetic disposable
fixtures. Run them through the isolated backend runner with an explicit file
selection. Its `BILLING_DATABASE_TESTS` and test DSNs are configured for you.

Stripe TEST keys, signed listener events and optional local Test Clocks are
separate explicit acceptance work; see [integrations](INTEGRATIONS.md#stripe-test-mode-optional).
No real payment or LIVE key belongs in a local smoke test.
Groq, image, search and merchant acceptance need independently authorized test
accounts and may consume provider resources or Credits. Existing CI workflows
with live-provider opt-ins are not ordinary offline tests. Do not fabricate
outputs or equate mocks with real external-provider success.

## Optional synthetic business data

`dev.ps1 seed` generates import files only; customers load them through normal
review/confirmation APIs. It is not automatic during installation.

For a larger coherent meeting fixture, committed
`tools/dev/seed_meeting_demo.py` supports `prepare`, `seed`, `verify` and has
focused tests in `tools/dev/tests/test_meeting_demo.py`. Read the
[Seed Truth Manifest](DEMO_SEED_PHASE1.md) before use. It creates fictional
products, invoices, closing stock, manual competitor observations and knowledge
documents in one designated tenant; it backs up and verifies restore before
seeding. Existing calculations and triggered forecasts are real, not canned AI.

Each fresh checkout needs its own generated private account/journal files.
The original tenant UUID, password location, trial dates and expected calendar
cards in the historical report describe that recorded installation. They are
not shared credentials or universal current-date expectations. Do not copy the
original private fixture, delete replay guards, or reseed an existing tenant to
make verification pass. Phase acceptance drivers can consume allowances and
create provider artifacts; they are not read-only setup tests.

The original verifier also compares protected file hashes against its retained
backup. An authorized change to a public `.env.example` can invalidate that old
file-hash assertion without changing business data. Report and explain the diff;
do not replace old backup evidence or turn a mismatch into a claimed pass.

## Recovery and evidence

The isolated runner stops its test processes/services when finished and retains
test DBs and logs. `dev.ps1 test-cleanup` only removes owned disposable test
containers; it is not a customer-data reset. See the
[test recovery reference](TEST_ENVIRONMENT_RECOVERY.md) for interrupted runs.

For each change report PASS, FAIL, BLOCKED or NOT TESTED with the exact command,
source revision, scope, expected versus actual outcome and remaining limits.
Never disable a guard or skip a failure to produce a green summary.
