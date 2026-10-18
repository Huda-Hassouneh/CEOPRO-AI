# KEEL Backend – QA Test Report

**Date:** 2026-10-17 · **Branch:** `KEEL_Test` · **Scope:** the whole backend **except** the RAG subsystem
and the competitor subsystem (those were deliberately excluded from this QA pass).
Strategy and risk ranking: [QA_TEST_STRATEGY.md](QA_TEST_STRATEGY.md).

## 1. Verdict

**No defects found in the in-scope product code.** Every in-scope test passes against a real database.
Five *tests* were fragile (depended on the developer's shell or a stale expectation) and were fixed.

| Run | Environment | Result |
|---|---|---|
| Offline (no services), whole tree | Python 3.13, macOS | **2154 passed**, 774 skipped (need DB), 0 failed |
| Live stack, in-scope tests | Postgres 16 + pgvector, Redis 7, MinIO, all 71 migrations applied | **2061 passed**, 16 skipped, 0 failed |
| Live stack, whole tree via `run_qa.sh full` | same | 2881 passed, 2 failed + 13 errors – **all in the excluded RAG/competitor areas** (§5) |
| Security contract only | no services | 339 passed |

## 2. What was added (all on `KEEL_Test`)

| File | Purpose | Priority |
|---|---|---|
| `src/ai/tests/test_api_security_contract.py` | Reads all **141** API operations from the OpenAPI schema. 12 are public by design (health, sign-in/sign-up/password/e-mail-verification/invitation flows, plan list); the other **129 must return 401** with no token and with a token signed by the wrong secret. The public list is pinned, so any new unauthenticated route fails the suite. Also: expired token, `alg=none`, HS512, malformed headers, missing/empty `tenant_id`/`user_id`, tenant taken only from the token (never query/header), DB connection closed on error, error body does not leak internals. | P0 |
| `src/infrastructure/tests/test_security_internal_token.py` | Internal service token: missing/empty, rotated token, static fallback, Redis down, no secret in error text. | P1 |
| `src/infrastructure/tests/test_token_rotator.py` | Rotation issues unique 64-hex tokens, old tokens enter a grace window, expired tokens are evicted, invalid input and Redis failure fail closed. | P1 |
| `src/infrastructure/tests/test_watchdog.py` | Alert thresholds (5 % error rate, 10 000 stream backlog), connection-lost alerts, webhook payload, webhook failure never raises. | P2 |
| `src/infrastructure/tests/test_backup_verifier.py` | Required settings, SHA-256 checksum, too-small snapshot rejected, `pg_dump` failure, restore passes/fails on table count, sandbox DB always dropped. | P2 |
| `scripts/run_qa.sh` | One command to run everything (§4). | – |
| `QA_TEST_STRATEGY.md`, `QA_TEST_REPORT.md` | This documentation. | – |

**Existing tests fixed** (test problems, not product bugs):
1. `conftest.py` now sets a throwaway `CREDENTIAL_VAULT_MASTER_KEY` – two onboarding tests returned 503 without it.
2. `conftest.py` now sets one `JWT_SECRET` for the whole run; `core/security.py` reads it once at import, and
   `test_main_integration_db.py` had signed its tokens with a different hard-coded secret (3 failures, order/shell dependent).
3. `test_main_integration_db.py` expected staged rows to stay `VALID`; upload promotes them to `COMMITTED`.

## 2b. CI findings (GitHub Actions, Python 3.11, pinned dependencies)

* **The backend tests had never run in CI on recent commits.** The "Audit Python dependencies" step failed first on
  `CVE-2026-106454` (Twisted IMAP *server* ReDoS). Twisted is only Scrapy's transitive dependency, nothing in the repo
  uses its mail/IMAP code, 26.4.0 is already the newest release and no fix exists. `pr-checks.yml` now ignores **only that
  one ID**, with the reason beside it (owner-approved). **Remove the ignore when Twisted ships a fix**; any other finding still fails the job.
* With the audit passing, CI ran the full suite on 3.11: **2908-2909 passed**. The remaining failures were:
  * 4 MinIO-backed tests (`test_plan_catalog_integration_db.py` x3, `test_marketing_lifecycle_integration_db.py` x1) that
    only checked for the database, so they failed where MinIO is absent. **Fixed:** they now skip without MinIO (and pass with it, verified both ways).
  * `test_competitor_enrichment_integration_db.py::test_due_mode_skips_permanent_misses_but_force_mode_retries_them_and_fixed_setup_blocks`
    failed in one CI run and passed in the next, and passed in 4 local runs, so it is **flaky** (competitor area, out of scope).
    **Not fixed - cause not reproduced.** If it recurs, the failing assertion is the first one ("due" mode picks the wrong set).

## 3. Observations worth knowing (no action required)

* RLS isolation tests (`test_rls_integration_db.py`) pass against a real Postgres with the restricted `ceopro_app` role.
* CI (`.github/workflows/pr-checks.yml`) already runs `pytest src/` with Postgres and Redis, so all new tests run on
  every PR. CI has no MinIO service, so MinIO-backed tests skip there (run `./scripts/run_qa.sh full` with MinIO to cover them).
* `/health/ready` returns 503 when dependencies are unreachable and is public; `/billing/plans` is public – both intentional.

## 4. How to run (nothing else to configure)

```bash
cd backend
pip install -r src/ai/requirements.txt pytest pytest-timeout   # once
./scripts/run_qa.sh security    # P0 only, seconds
./scripts/run_qa.sh             # all offline tests, ~30 s
./scripts/run_qa.sh full        # + live DB/Redis/MinIO
```

* `full` uses `DATABASE_URL` if set (it then applies migrations itself and needs `APP_DB_PASSWORD`);
  otherwise it needs Docker and starts `postgres redis minio` from `docker-compose.yml`, runs `migrate`, then tests.
* macOS: `brew install libomp` once (xgboost). Extra pytest arguments can be appended, e.g. `./scripts/run_qa.sh unit -k pricing`.
* The script sets `OMP_NUM_THREADS=1` and `KMP_DUPLICATE_LIB_OK=TRUE`; without them torch and xgboost (two OpenMP runtimes)
  can hang a sentiment model test on macOS.

## 5. Known limitations – read before relying on this

1. **Not run in a Codespace or on Docker.** The live-stack run used Postgres/Redis/MinIO binaries installed locally,
   not the `docker-compose.yml` images (Postgres 15 in compose vs 16 here). The `docker compose` branch of
   `run_qa.sh full` is written from the compose file but **has not been executed**; the `DATABASE_URL` branch has.
2. **Excluded areas have open test failures** (found by the whole-tree run, not investigated or fixed):
   * `test_dashboard_competitors_integration_db.py::test_last_updated_reflects_the_real_classified_at_timestamp` –
     timestamp expectation is timezone-dependent (got `+03:00`, expected UTC) – fails on any machine not on UTC.
   * `test_competitor_enrichment_integration_db.py::test_due_mode_skips_permanent_misses_but_force_mode_retries_them…` – a set-equality assertion on competitor ids.
   * 13 RAG errors (`test_rag_integration.py`, `test_structured_summaries_integration_db.py`) were MinIO signature
     errors from this run's endpoint/credential setup (RAG expects a scheme-less endpoint, the upload tests a URL) – an
     environment mismatch in the run, not shown to be a code defect.
3. **Model-quality tests were not run:** `*_real.py` (real sentiment weights) need model downloads; backtesting quality is not asserted here.
4. **Load, performance and browser/UI testing are out of scope** for this pass (`frontend/tests/browser/smoke.mjs`
   and `scripts/load_test.py` exist and run separately).
5. Tests were run on Python 3.13; CI uses 3.11 and `src/ai/requirements.txt` pins (numpy<2, pandas<3) were not
   installed exactly as pinned locally (numpy 2.x / pandas 3.x were used). CI is the authority for the pinned set.
