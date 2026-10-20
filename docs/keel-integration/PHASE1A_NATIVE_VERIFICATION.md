# Phase 1A verification runbook

Current result: INTEGRATION BLOCKED. No native PostgreSQL/Redis/SMTP/provider tests, migrations or browser application journeys were run in this session. Missing services are not repeatedly probed. Parser/double-based checks cannot close these gates. Commands below require a separate capable environment and dedicated disposable fixtures.

## Exact source and dependencies

Use this Phase 1A delivery atop the preserved Task 6 baseline. Reconcile the starting manifest, incremental diff and candidate hashes in `evidence/phase1a`; record the exact candidate actually tested. HEAD alone omits the incoming Task 6 repairs. Requirements: native PostgreSQL **17** + pgvector, at least eight independent sessions, Redis 7.4, SMTP test capture, configured restricted ceopro_app login and a schema-owner migration identity. Existing full application tests also need the existing AI/scraper dependencies. Install the repository's `backend/src/ai/requirements.txt`, `backend/src/market_scraper/requirements.txt` and `backend/tests/billing/requirements.txt` in the supported runtime; do not alter production behavior to avoid dependencies. Current main-app collection failed on missing Scrapy; prior Phase 0V identified other model/metrics dependencies. The documented runtime is Python 3.11; these isolated checks used Python 3.12.14 / Node 24.19.0. Validate the supported release runtime separately.

## Supported checks — already run

From backend in an installed isolated environment without live credentials:

```bash
python -m scripts.phase1a_verification --junitxml phase1a-unit.xml
python -m scripts.integration_review --junitxml existing-regression.xml
```

From frontend:

```bash
npm test
npm run build
npx --no-install eslint src/features/platform src/features/auth/pendingRegistration.js tests/phase1a.test.mjs
```

Exact session command arrays, environment isolation, timings and exits are retained in `evidence/phase1a`. The test launcher keeps native tests disabled unless requested, rejects live Stripe keys and uses production metering defaults. DB/Redis/mail doubles prove contract behavior only. This session also removed inherited service credentials and used a scratch TCP fence. Ruff was unavailable; run the repository's configured Python lint before release.

## Disposable services and migrations — NOT RUN

From backend, assign strong test-only values to BILLING_TEST_ADMIN_PASSWORD, APP_DB_PASSWORD and PHASE1A_REDIS_TEST_PASSWORD through a secret mechanism. Do not save/print credentials. These Compose files bind loopback and use disposable tmpfs rather than customer volumes.

```bash
docker compose -p keel-phase1a-verify -f tests/billing/docker-compose.yml -f tests/keel_integration/docker-compose.yml up -d
```

Set BILLING_TEST_DATABASE_URL to `postgresql://keel_billing_test_admin:<URL-encoded-test-secret>@127.0.0.1:55439/keel_billing_test` and PHASE1A_ISOLATED_DATABASE=YES. Placeholders are not executable credentials. The guard refuses remote hosts, arbitrary database names, missing acknowledgment and BILLING_TEST_ENGINE; DATABASE_URL is never a fallback.

Fresh rehearsal on the new database (no companies table):

```bash
python -m scripts.phase1a_migration_rehearsal --mode fresh --output phase1a-native-fresh.json
```

Create a second new disposable database `keel_billing_test_p1upgrade` in this dedicated cluster through the test-admin workflow. Point BILLING_TEST_DATABASE_URL to it; use the same APP_DB_PASSWORD because ceopro_app is cluster-wide:

```bash
python -m scripts.phase1a_migration_rehearsal --mode populated --output phase1a-native-populated.json
```

The rehearsal uses the existing migration runner: previous 78 migrations, historical identity/hash/membership/metered receipt and numeric-code fixtures, then only the new migration. It asserts preserved values and repeat-run no-op. Both modes export actual role/table/policy/function owner/ACL/search_path catalogs and refuse an existing companies table. Neither creates/drops databases. Historical subscription/trial/contract compatibility additionally requires the existing billing/Task 6 native suites and release-candidate fixture comparisons; the rehearsal alone does not prove it.

On the migrated disposable DB, configure APP_DB_PASSWORD, PHASE1A_REDIS_TEST_URL (`redis://:<URL-encoded-test-secret>@127.0.0.1:56379/15`), PHASE1A_ISOLATED_REDIS=YES and the existing isolated DB environment:

```bash
python -m scripts.phase1a_verification --database --junitxml phase1a-native.xml
python -m scripts.integration_review --database --junitxml existing-native.xml
```

Prepared source: `tests/keel_integration/test_native_phase1a.py` (15 cases), `test_redis_phase1a.py` (one Redis/DB case), existing `tests/remediation/test_native_concurrency.py` and integration-review/runtime-role suites. Cases cover zero permanent identity before verification, eight-session once-only creation, DB guess limits/expiry, direct table/FORCE RLS grants, customer-owner denial, admin financial denial/audit, owner idempotency/last owner, suspended-company RLS, concurrent owner transfer, per-workspace suspension, existing identity/password reuse, credential-version/membership compatibility and cross-account code collision.

The Redis case performs real TTL/write/read and removes only its own random cache key to prove durable receipt lookup on a cache miss. Its outage boundary is an explicit double, **not actual process-outage proof**. In the disposable running application stack, stop/restart only that test Redis service: protected reads/writes/refresh must return503 during outage, revoked tokens must remain401 after restart, and signout must report unconfirmed server revocation honestly. Repeat with DB unavailability. Record versions/HTTP outcomes/timestamps without secrets; do not use shared services.

## Full application, RLS and browser gates

After installing existing dependencies, collect/run `src/ai/tests/test_auth.py`, `test_auth_completeness.py`, `test_auth_signup_integration_db.py`, `test_rls_integration_db.py`, settings/session/team suites and existing integration-review suites against isolated fixtures. Current collection produced two missing-Scrapy import errors and 21 collected tests, with no execution. Existing tests assuming immediate permanent signup or unconditional mocked revocation may require approved-contract updates; do not weaken production guards to satisfy older assumptions.

For browser smoke, run an isolated local frontend/API with migrated DB, Redis and SMTP sink. Set PHASE1A_ISOLATED_BROWSER=YES, PHASE1A_BROWSER_BASE_URL to the loopback frontend and PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH. Optionally provide PHASE1A_BROWSER_INVITATION_TOKEN for an existing disposable user invited as admin. Never supply production sessions or invitations.

```bash
node tests/browser/phase1a.mjs
```

The executable smoke covers anonymous platform redirect, invalid invitation and optional existing-user admin acceptance/dashboard with owner-approval UI absent. The following remain **manual acceptance obligations, not automated browser coverage**: signup zero permanent rows before captured code; failed mail/resend; wrong/expired/duplicate verification; onboarding/trial result; existing unverified account; workspace-choice/switch/create; refresh max age/expiry; reset/change-password reauthentication; customer invite one-use/capacity; company/account/membership isolation; operator resend/cancel/expiry/issuer removal; owner transfer/role refresh; cache isolation across signout/relogin; bilingual dashboard mutations/audit/profile/security. Automate these as the capable stack becomes available; smoke alone cannot certify them.

Release gates: fresh/populated/repeat migrations PASS; native PG17 function compilation/owner/grants/FORCE RLS/catalog/runtime-role login PASS; concurrency and Task 6 accounting regressions PASS; real Redis/DB outage/recovery PASS; full application auth/settings regressions PASS; SMTP and browser journeys PASS; lint; no unresolved security defects; ledger reconciled against the exact reviewed candidate. Stripe/provider/worker certification remains separate before any later commercial/provider release. No deployment is authorized.
