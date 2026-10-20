# Phase 1A verification runbook

Current result: native database and Redis verification passed on 2026-10-20 using isolated disposable services. The legacy authentication unit suites now pass (42 passed), the approved auth-contract suite passes (34 passed), and the native Phase 1A PostgreSQL suite passes (18 passed). These results do not establish production readiness. SMTP delivery, browser journeys, settings/team suites, Python 3.11, and persistent-storage database outage recovery remain unverified.

## Exact source and dependencies

Use this Phase 1A delivery atop the preserved Task 6 baseline. Reconcile the starting manifest, incremental diff and candidate hashes in `evidence/phase1a`; record the exact candidate actually tested. HEAD alone omits the incoming Task 6 repairs. Requirements: native PostgreSQL **17** + pgvector, at least eight independent sessions, Redis 7.4, SMTP test capture, configured restricted ceopro_app login and a schema-owner migration identity. Existing full application tests also need the existing AI/scraper dependencies. The native checks below used Python 3.12.7; the documented Python 3.11 runtime remains unverified. No project dependency manifest was changed.

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

## Disposable services and migrations — completed

The tested Compose project was `keel-phase1a-native-20261020`, with PostgreSQL bound only to `127.0.0.1:55439` and Redis to `127.0.0.1:56379`. Both services used disposable tmpfs storage. Credentials were generated for this test run, held outside the repository, and were not printed or committed. No shared database, the listener on port 5432, `.env`, Stripe, or external provider was used.

```bash
docker compose -p keel-phase1a-verify -f tests/billing/docker-compose.yml -f tests/keel_integration/docker-compose.yml up -d
```

The verification guard accepts only local `keel_billing_test` names with lowercase suffixes, or the explicitly required `KEEL_INTEGRATION_TEST` name with uppercase suffixes (the upgrade fixture used `_UPGRADE`). It rejects remote hosts, other database names, missing isolation acknowledgment, and `BILLING_TEST_ENGINE`; `DATABASE_URL` is never a fallback.

Fresh rehearsal on `KEEL_INTEGRATION_TEST` passed: 79 migrations applied, repeat run applied 0. PostgreSQL reported 17.11 and pgvector 0.8.7. The migration catalog contained 79 rows and confirmed this ordering:

1. `20261020000000_keel_subscriptions_and_credits.sql`
2. `20261024000000_report_request_identity.sql`
3. `20261025000100_integration_principal_permissions.sql`

The populated-upgrade rehearsal on `KEEL_INTEGRATION_TEST_UPGRADE` passed: 78 baseline migrations, then only `20261025000100_integration_principal_permissions.sql`; historical compatibility assertions passed and the repeat run applied 0.

To reproduce the fresh rehearsal on a new isolated database (no companies table):

```bash
python -m scripts.phase1a_migration_rehearsal --mode fresh --output phase1a-native-fresh.json
```

Create a second new disposable database `keel_billing_test_p1upgrade` in this dedicated cluster through the test-admin workflow. Point BILLING_TEST_DATABASE_URL to it; use the same APP_DB_PASSWORD because ceopro_app is cluster-wide:

```bash
python -m scripts.phase1a_migration_rehearsal --mode populated --output phase1a-native-populated.json
```

The populated rehearsal uses the existing migration runner, historical identity/hash/membership/metered-receipt and numeric-code fixtures, and then only the new migration. It asserts preserved values and repeat-run no-op. Both modes export actual role/table/policy/function owner/ACL/search_path catalogs and refuse an existing companies table. Neither creates nor drops databases. The native billing/Task 6 regressions also passed below; a separate release-candidate fixture comparison for historical subscription/trial/contract data remains unverified.

On the migrated disposable DB, configure APP_DB_PASSWORD, PHASE1A_REDIS_TEST_URL (`redis://:<URL-encoded-test-secret>@127.0.0.1:56379/0`), PHASE1A_ISOLATED_REDIS=YES and the existing isolated DB environment. Results on PostgreSQL 17.11/pgvector 0.8.7 and Redis 7.4:

```bash
python -m scripts.phase1a_verification --database --junitxml phase1a-native.xml
python -m scripts.integration_review --database --junitxml existing-native.xml
python -m pytest -q src/ai/tests/test_rls_integration_db.py
python -m pytest -q tests/keel_integration/test_redis_phase1a.py
```

Earlier native verification recorded: `phase1a_verification --database` — 72 passed; `integration_review --database` — 154 passed; direct application-role RLS suite — 18 passed; live Redis revocation test — 1 passed. These four results are retained from the earlier native verification run and were **not rerun during the authentication test-remediation pass**. The first two commands each emitted one Starlette/httpx deprecation warning. The native cases cover pre-verification identity creation, eight-session once-only creation, code attempt limits/expiry, platform grants and FORCE RLS, customer-owner denial, admin financial denial/audit, owner idempotency/last-owner protection, suspended-company access, concurrent owner transfer, per-workspace suspension, existing identity/password reuse, credential-version/membership compatibility, cross-account code collision, billing delivery claims, HTTP usage enforcement, and concurrency. `integration_review` also passed native `ceopro_app` password authentication. The separate RLS suite used actual `ceopro_app` password connections and passed cross-tenant visibility, no-context, removed-membership, and RAG isolation checks.

### Legacy authentication regression follow-up — completed

The first run of `src/ai/tests/test_auth.py` and `src/ai/tests/test_auth_completeness.py` produced 21 passed and 21 failed. Review found 3 obsolete expectations (immediate permanent signup and HTTP 400 for missing invite credentials) and 18 test-fixture problems (unconfigured active-principal mocks, non-UUID identities, stale token/cursor helpers, or mock results that did not match the current SQL-function JSON contract). No production authentication defect was confirmed. The tests were updated without changing authentication source code.

Exact follow-up results on the isolated Python 3.12.7 interpreter:

```bash
python -m pytest -q src/ai/tests/test_auth.py src/ai/tests/test_auth_completeness.py
```

**42 passed**, one Starlette/httpx deprecation warning. This covers refresh age/membership/legacy `auth_time`, pending signup and delivery failure, logout delegation, reset/email code helpers, account enumeration, throttling and customer invite contract responses.

```bash
python -m pytest -q tests/keel_integration/test_auth_phase1a.py
```

**34 passed**, one Starlette/httpx deprecation warning.

```bash
python -m pytest -q tests/keel_integration/test_native_phase1a.py
```

**18 passed**, one Starlette/httpx deprecation warning. This rerun adds eight-session duplicate-registration coverage (one pending, seven conflicts), real PostgreSQL-backed password reset with account-bound one-use codes and credential-version update, and public customer-invitation acceptance for both existing and new users. Its HTTP test connections explicitly `SET ROLE ceopro_app`; the earlier 154-test `integration_review` separately verified native `ceopro_app` password authentication. The tests used isolated disposable PostgreSQL and did not send email or contact external providers.

The Redis test performs real TTL/write/read and removes only its own random cache key to prove durable receipt lookup on a cache miss. In addition, a real isolated Redis stop/start returned HTTP 503 for revocation checks while Redis was down; after restart, the PostgreSQL durable receipt still identified the revoked token and an unknown token remained unrevoked. A real isolated PostgreSQL stop returned HTTP 503 for revocation checks. PostgreSQL's test data is on tmpfs, so restarting its container discarded the disposable cluster; the databases were recreated and migrations and test suites rerun. This verifies fail-closed behavior and fresh-cluster recovery, not persistence across a production PostgreSQL restart. No real SMTP outage or browser HTTP journey was exercised.

## Remaining full-application and browser gates

The direct `src/ai/tests/test_rls_integration_db.py` suite passed as noted above, and both legacy auth unit suites and the focused Phase 1A auth/native suites now pass. The live `test_auth_signup_integration_db.py`, settings/session/team suites, SMTP capture, and browser journeys were not run. Do not send email or contact providers during verification. The resolved legacy failures required test-contract/fixture updates only; do not weaken production guards to satisfy obsolete expectations.

For browser smoke, run an isolated local frontend/API with migrated DB, Redis and SMTP sink. Set PHASE1A_ISOLATED_BROWSER=YES, PHASE1A_BROWSER_BASE_URL to the loopback frontend and PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH. Optionally provide PHASE1A_BROWSER_INVITATION_TOKEN for an existing disposable user invited as admin. Never supply production sessions or invitations.

```bash
node tests/browser/phase1a.mjs
```

The executable smoke covers anonymous platform redirect, invalid invitation and optional existing-user admin acceptance/dashboard with owner-approval UI absent. The following remain **manual acceptance obligations, not automated browser coverage**: signup zero permanent rows before captured code; failed mail/resend; wrong/expired/duplicate verification; onboarding/trial result; existing unverified account; workspace-choice/switch/create; refresh max age/expiry; reset/change-password reauthentication; customer invite one-use/capacity; company/account/membership isolation; operator resend/cancel/expiry/issuer removal; owner transfer/role refresh; cache isolation across signout/relogin; bilingual dashboard mutations/audit/profile/security. Automate these as the capable stack becomes available; smoke alone cannot certify them.

Release gates: fresh/populated/repeat migrations PASS; native PG17 function compilation/owner/grants/FORCE RLS/catalog/runtime-role login PASS; auth unit, approved auth-contract, native auth/platform, executed concurrency and Task 6 accounting regressions PASS; real Redis/PostgreSQL outage fail-closed checks PASS. Persistent-storage PostgreSQL restart recovery, settings/session/team suites, SMTP and browser journeys, Python 3.11, lint, unresolved security review, and ledger reconciliation against a release candidate remain open. Stripe/provider/worker certification remains separate before any later commercial/provider release. No deployment is authorized.
