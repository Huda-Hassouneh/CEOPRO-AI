> Current Phase 1A update (2026-10-20): the owner explicitly authorized bounded production authentication/platform implementation in an isolated copy. Historical Phase 0/0R/0V statements about missing implementation permission describe their original stage. Current source, limits and actual tests: [PHASE1A_IMPLEMENTATION_REPORT.md](PHASE1A_IMPLEMENTATION_REPORT.md). Native verification and production release remain blocked.

# Tests and verification actually executed

Date: 20 October 2026. Scope: documentation-only Phase 0 against frozen supplied content, **not an implemented migration acceptance run**. No user/shared/production database or provider account was contacted.

| Check | Command / cwd | Actual result | Evidence |
|---|---|---|---|
| Backend guarded pure/contract baseline | `python -m scripts.integration_review --junitxml <scratch>/analysis/backend-baseline.xml` from backend, using isolated verification venv | **56 passed, 94 skipped, 0 failed**, 1 nonfatal test-client deprecation warning; exit 0 | evidence/backend-baseline.log and .xml |
| Initial frontend without installed deps | `node --test tests/*.test.mjs` from frontend | 40 passed, 15 failed (missing axios/dependencies), 55 reported tests; exit 1 | evidence/frontend-baseline.log |
| Frontend dependency installation | `npm ci --ignore-scripts --no-audit --no-fund` | 309 packages installed outside tracked source; lockfile unchanged | Scratch install log; no source modifications |
| Frontend corrected baseline | `node --test tests/*.test.mjs` from frontend | **90 passed, 0 failed, 0 skipped**, exit 0 | evidence/frontend-installed.log |
| Frontend build | `npm run build` from frontend | **PASS**, exit 0, Vite build completed | evidence/frontend-build.log |
| Source indexing | Python stdlib AST, lexical TS/JS import/route extraction and ordered SQL statement scan | Generated indexes; one infrastructure ai_consumer.py has leading BOM, AST initial parse not accepted; do not interpret as runtime failure | FUNCTION_CALL_INDEX, IMPORT_GRAPH, ROUTE_CANDIDATES and SQL_OBJECT_LINEAGE |
| Phase 0 document integrity | `python docs/keel-integration/evidence/verify_phase0.py --python-root . --node-root <read-only-node-root>` | See evidence/PHASE0_VERIFICATION.json; original byte checks, 21-code crosswalk, unique capability IDs, source paths, docs ledger set/actions and relative links | Generated final verification JSON |

The initial frontend failure was environmental and resolved by installing the archive's locked dependencies. It is not hidden as a production fix. No frontend source/package/lockfile was changed. Full backend/AI dependencies were not installed and full model suite was not executed. No generated frontend dist or venv is part of the deliverable.

## Task 6 prior evidence — not this run

Supplied report and docs/remediation/test_results.xml state 140 passed, 10 skipped, on a disposable **PGlite PostgreSQL 17.5** run; 78 migrations applied fresh and zero repeat. Preserve those original logs and source-integrity metadata. Their native/Stripe/model/Redis/populated-upgrade limitations remain exactly as reported. This Phase 0 did **not** reproduce those DB results, nor convert PGlite into native concurrency evidence.

Native cases previously skipped include concurrent duplicate webhooks; runtime-role password login; last-unit reservation race; three staff HTTP mutations using multiple connections; two full HTTP upgrade/downgrade cases; two concurrent HTTP report cases. Native test functions exist under backend/tests, but existence is not a passing result.

## Reconciled local checkout verification

These results are from the local `integration/keel-task6-phase1a` checkout, not the historical Phase 1A archive results above.

| Check | Command / environment | Actual result |
|---|---|---|
| Backend integration review | `python -m scripts.integration_review` from `backend`, with `PYTHONUTF8=1` | **110 passed, 110 skipped**. With Windows' default encoding, three source-inventory tests failed because UTF-8 source was decoded as cp1252; the UTF-8 rerun passed. |
| Full frontend suite before the path fix | `npm test` from `frontend` | **93 passed, 1 failed**. `locales.test.mjs` passed a URL-encoded Windows `.pathname` to filesystem traversal (`C:\C:\...` / `%20`); this was a test portability issue, not a localization or application defect. |
| Full frontend suite after the path fix | `npm test` from `frontend` | **94 passed, 0 failed, 0 skipped**. The test now converts its file URL with Node's `fileURLToPath()`. |
| Focused authentication frontend tests | `node --test tests/phase1a.test.mjs` from `frontend` | **4 passed**. |

The frontend suite was rerun after the test-only path correction. PostgreSQL 17, Redis, RLS, concurrency, and end-to-end verification remain pending; these local results do not establish production readiness.

## Tests NOT RUN and release effect

- Native PostgreSQL 17 server/multi-session HTTP/RLS/password login and populated migration rehearsal: **BLOCKED**, server tools/Docker unavailable. No SQLite/PGlite substitute was used to assert success.
- Live Redis worker/outbox/revocation isolation and multiple API replicas: NOT RUN.
- Real Stripe TEST Checkout/Webhooks/Test Clock/SCA/currency flows: NOT RUN; no test credentials/resources supplied. Signature fixtures are not provider certification.
- Authorized Shopify development-store and WooCommerce sandbox E2E: NOT RUN; dedicated target adapters do not yet exist and no credentials supplied.
- Full app startup/model inference/original full backend/market worker suite: NOT RUN, full binary/model dependencies and isolated infrastructure absent.
- Browser UI→API→worker→database E2E/screenshots: NOT RUN; frontend unit contracts/build only, no live backend/database/model server.
- Proposed migration DDL and every `AT-*` case: NOT RUN/NOT IMPLEMENTED. They are specifications in ACCEPTANCE_TEST_SPEC.csv, not executable tests yet. Each approved implementation phase must write and execute concrete corresponding tests under existing guarded fixtures.

## Executable next verification

Use backend/tests/billing/docker-compose.yml to provision dedicated disposable PG17 with locally chosen test credentials, not KEEL_DEV or shared production. In a clean approved checkout:

```bash
cd backend
python -m venv .venv-verification
.venv-verification/bin/python -m pip install -r tests/billing/requirements.txt
# Configure BILLING_TEST_DATABASE_URL locally for the guarded disposable test cluster.
.venv-verification/bin/python -c 'import os; from scripts.billing_verification import validate_test_environment; validate_test_environment(dict(os.environ), database=True)'
# Configure DATABASE_URL/APP_DB_PASSWORD for that same isolated cluster/migration role,
# preserving existing application credentials outside this test environment.
.venv-verification/bin/python -m scripts.apply_migrations
.venv-verification/bin/python -m scripts.integration_review --database --junitxml remediation-native.xml
```

The guard must pass before migration. Do not copy a production DSN or disable safety guards. Run migration a second time and assert no new applications; rehearse populated historical report-key schema upgrade and locks; test runtime ceopro_app password login separately from SET ROLE; log pg version/current_user/rolsuper/rolbypassrls without secret values. No amount of unit passing bypasses these native conditions.

Full regression after dependencies/model fixtures: `python -m pytest -q src/` from backend, `npm test`, `npm run build`, `npm run test:browser` from frontend using approved disposable services/test accounts. Existing tests that hit provider networks must follow their opt-in controls. Never invoke seeds/scripts against a shared database just to produce attractive UI data.


## Phase 0R refinement

See [PHASE0R_README.md](PHASE0R_README.md), [SOURCE_SNAPSHOT_RECONCILIATION.md](SOURCE_SNAPSHOT_RECONCILIATION.md), [SCHEMA_VERIFICATION.md](SCHEMA_VERIFICATION.md) and [DOMAIN_READINESS.md](DOMAIN_READINESS.md). Exact capability source roots, real schema lineage and thirteen concrete owner questions have been refined; no implementation or approval occurred. Earlier 56-pass/94-skip backend and 90-pass frontend/build logs are prior Phase 0 evidence, not rerun Phase 0R acceptance. SOURCE-001 and VERIFY-001 remain blocked. Raw lexical DB evidence is nonauthoritative.
