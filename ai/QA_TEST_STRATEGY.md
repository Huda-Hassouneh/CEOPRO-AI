# CEOPRO AI – QA Test Strategy (risk-based)

**Scope:** everything under `backend/src/` **except** the RAG subsystem (`src/ai/rag/**`, `/rag/query`) and the
competitor subsystem (competitor discovery/classification/enrichment/dashboards and their tests).
**Date:** 2026-10-17.

## 0. First execution results (2026-10-17, KEEL_Test, no Docker)

* New P0 route sweep covers all **141** API operations (read from the OpenAPI schema): 12 are public by
  design (health, sign-in/password/verification/invitation flows, plan list), the other 129 reject missing
  and forged tokens with 401. The allow-list is pinned, so any new open route fails the suite.
* 278 security-contract tests + 7 internal-token tests pass. DB-backed (`*_integration_db.py`) tests need
  the Codespace stack and are the next run.

## 1. Approach

Test effort is allocated by **risk = likelihood of defect × business/security impact**. Each area gets a
priority (P0–P3) and a test level. Cheap, offline, deterministic tests run on every commit; DB-backed
(`*_integration_db.py`) tests run in CI against Postgres/Redis/MinIO from `docker-compose.yml`.

| Level | Where | Runs |
|---|---|---|
| L1 Unit (pure logic, mocks) | `src/**/tests/test_*.py` | every commit, no services |
| L2 API contract (FastAPI `TestClient`, DB mocked) | `src/ai/tests/test_main.py`, `test_api_security_contract.py` | every commit |
| L3 Integration (real Postgres/RLS/Redis/MinIO) | `*_integration_db.py` | CI with compose stack |
| L4 Model quality (real weights, backtests) | `*_real.py`, `test_backtesting.py` | nightly / pre-release |

## 2. Risk register and priorities

| Pri | Area | Why it is risky | Key test focus | Status |
|---|---|---|---|---|
| **P0** | AuthN/AuthZ: JWT tenant context (`main.get_tenant_context`), internal service token (`security.py`) | Single gate for every endpoint; failure = cross-tenant data exposure | Missing/malformed/expired/forged/`alg=none`/wrong-secret tokens, missing claims, **every route requires auth (auto-discovered)**, tenant taken only from token never from request params | New: `test_api_security_contract.py` |
| **P0** | Multi-tenant isolation (RLS, `db.app_role_connection`) | Known history of RLS defects (RED_FLAGS.md) | Two-tenant read/write isolation, fail-closed with no context | Exists (`test_rls_integration_db.py`, needs DB) |
| **P0** | File upload / extraction (`/extraction/upload`, `extraction/**`) | Untrusted input, large files, data-integrity of products/sales | Size cap, magic bytes, extension spoof, empty file, malformed rows, locale/number parsing, dedupe, commit batching | Exists; add edge cases (see §4) |
| **P0** | Scraper safety: policy, network security (SSRF), content safety, credential vault | Legal/compliance + SSRF + secret leakage | Deny-by-default policy, private-IP/redirect blocking, encryption round-trip | Exists (`test_policy`, `test_network_security`, `test_credential_vault`, `test_content_safety`) |
| **P1** | Pricing recommendation + guardrails + currency | Wrong price advice = direct revenue impact | Margin floor, max change, currency conversion, missing cost | Exists; boundary tests to add |
| **P1** | Forecasting (features, model, baselines, backtesting, consumer) | Silent bad forecasts; consumer message handling | Feature leakage, cold start, bad stream messages, retry/ack | Exists |
| **P1** | Persistence / cost ledger / enqueue cost gate / search quota | Money (API spend) and data integrity | Gate thresholds, quarantine vs promote, idempotency | Exists (unit + DB) |
| **P1** | Connectors (DB/API sync), onboarding | Customer credentials + external calls | Validation, SSRF on `base_url`, credentials never echoed | Exists; contract test to add |
| **P2** | Dashboard endpoints (metrics, forecast, inventory, search, activity) | Read-only, but wrong numbers erode trust | Param bounds (422), empty-tenant results, pagination | Exists (DB); auth sweep covers 401 |
| **P2** | Sentiment, MPI, insights | ML/heuristic output quality | Scoring math, cold start, thresholds | Exists |
| **P2** | Infra: db_pool, messaging, monitoring, backup verifier | Availability | Pool exhaustion, reconnect, token rotation grace | Partial (db_pool only) |
| **P3** | Sales quick-sale, templates, CLI helpers | Low blast radius | Happy path + validation | Exists |

## 3. Entry / exit criteria

* **Entry:** `JWT_SECRET` set; deps from `src/ai/requirements.txt` + `src/market_scraper/requirements.txt`.
* **Exit for a release:** 0 failing L1/L2; all P0 L3 green in CI; no open P0/P1 defects; new endpoints
  automatically covered by the auth sweep.

## 4. Gaps identified and their status

| # | Pri | Gap | Status |
|---|---|---|---|
| 1 | P0 | No test enumerated all routes for auth; a new route could ship unauthenticated | **Done** - `test_api_security_contract.py` (141 operations from OpenAPI, pinned public list of 12) |
| 2 | P0 | JWT edge cases (expired, `alg=none`, HS512, empty claims) | **Done** |
| 3 | P0 | Nothing proved the tenant comes only from the token | **Done** |
| 4 | P1 | `security.py` internal-token verification untested | **Done** - `test_security_internal_token.py` |
| 5 | P1 | Token rotation grace window / eviction untested | **Done** - `test_token_rotator.py` |
| 6 | P2 | `watchdog.py` and `backup_verifier.py` untested | **Done** - `test_watchdog.py`, `test_backup_verifier.py` |
| 7 | P1 | CI did not run the suite | **Not a gap on KEEL_Test** - `.github/workflows/pr-checks.yml` already runs `pytest src/` against Postgres + Redis, so all new tests run in CI automatically |
| 8 | P2 | Tests depended on the developer's shell (vault key, JWT secret) and one expected `VALID` instead of `COMMITTED` | **Done** - fixed in `conftest.py` / `test_main_integration_db.py` |
| 9 | - | MinIO-backed tests are skipped in CI (no MinIO service) | **Open, low risk** - run locally with `./scripts/run_qa.sh full` |

## 5. How to run

```bash
cd backend
./scripts/run_qa.sh security   # P0 auth/security contract only (seconds)
./scripts/run_qa.sh            # all offline tests (~30 s, no services)
./scripts/run_qa.sh full       # + live Postgres/Redis/MinIO tests (docker compose, or your own DATABASE_URL)
```

Details, results and known limitations: see `QA_TEST_REPORT.md`.
