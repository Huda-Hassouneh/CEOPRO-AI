# Phase 0V native foundation verification

**Verdict: BLOCKED. Native PostgreSQL verification NOT RUN.** Correct working content was verified; clean reviewed commit, disposable PG17 infrastructure and complete runtime dependency environment were not established. No production implementation, migration application, DB connection or provider operation occurred.

## 1. Runtime and isolation preflight

Reviewed `backend/tests/billing/docker-compose.yml`: pgvector/pgvector:pg17, dedicated `keel_billing_test`, dedicated test admin, loopback port default 55439, tmpfs data directory and required locally supplied disposable password. Reviewed guarded `scripts/billing_verification.py` and `scripts/integration_review.py`: reject live Stripe keys and nonlocal/non-test URLs; never fall back from BILLING_TEST_DATABASE_URL to an application DB. These guards are necessary but cannot alone prove that a real cluster is disposable.

This environment has **no docker, podman, postgres, initdb, pg_ctl or psql executable**, no known native installation directory and no Docker/Podman socket. No isolated server/image digest, PG17 minor version, runtime-role login, role ACL or current database could be observed. No DSN/credential was requested, copied or substituted; no shared database was contacted. `integration_review --database`, migration runner and catalog probes were deliberately **NOT RUN**. No PGlite/WASM or parser was used as a substitute.

The old isolated test virtualenv interpreter symlink points to a missing prior runtime. Initial backend/auth launches failed before tests. The current Python interpreter plus existing scratch test site-packages restored offline tooling without changing repository dependencies. Exact tooling issue and resolution are in [TOOLING_PREFLIGHT.json](evidence/phase0v/TOOLING_PREFLIGHT.json). [TEST_ENVIRONMENT.json](evidence/phase0v/TEST_ENVIRONMENT.json) records actual versions, including Python `3.12.14`, pytest `9.1.1`, Stripe SDK `15.6.1`, Node `v24.19.0` and npm `11.9.0`. No Redis server was provisioned or verified.

## 2. Executed checks and exact outcomes

| Check | Passed | Assertion failures | Collection errors | Skipped | Exit / evidence |
|---|---:|---:|---:|---:|---|
| Existing guarded integration_review, offline | 56 | 0 | 0 | 94 | 0; backend.log, backend-offline.xml |
| Existing main auth tests (two modules) | 0 | 0 | 2 | 0 | 2; auth.log, auth-offline.xml |
| Six existing worker/connector/network test modules, continue-on-collection-errors | 24 | 0 | 3 | 0 | 1; workers.log, workers-offline.xml |
| Frontend npm test | 90 | 0 | 0 | 0 | 0; frontend-test.log |
| Frontend Vite build | n/a | n/a | n/a | n/a | 0; frontend-build.log; output only in scratch |
| Native PG17 / schema / RLS / concurrency / migrations | 0 | — | — | NOT RUN | no isolated native runtime |
| Provider certification / browser E2E | 0 | — | — | NOT RUN | separate release gate |

Exact executable argv/cwd/profile/exit/duration for each command are the `*-command.json` files under evidence/phase0v/. Full JUnit per-case evidence and [case status/skip reasons](evidence/phase0v/TEST_CASE_RESULTS.csv) remain authoritative; backend raw stdout ends in progress rather than a final summary. No output text was reconstructed as if emitted by pytest. The frontend build exits successfully and its generated index/assets remain outside the repository; it is not browser or API testing.

Commands executed from backend: current Python `-m scripts.integration_review --junitxml <evidence>/backend-offline.xml`; `-m pytest -q -ra -p no:cacheprovider src/ai/tests/test_auth.py src/ai/tests/test_auth_completeness.py --junitxml <evidence>/auth-offline.xml`; and six explicit market_scraper test modules with `--continue-on-collection-errors` (see workers-command.json). From frontend: `npm test`; `npm run build -- --outDir <scratch>/frontend-dist --emptyOutDir`.

All verification subprocesses used an allowlisted environment without inherited DB/provider secrets. Python TCP sockets were fenced by scratch-only sitecustomize; offline model/background flags were set, with `KEEL_TEST_DISABLE_METERING=0` and `UNASSIGNED_PLAN_ACCESS=none`. Existing test-local doubles and monkeypatches are not native/provider proof. The guarded combined suite's 94 skips are due to database mode being disabled, not passes; prior Task 6's 140/10 PGlite result remains historical. The 24 passing connector/network cases do not mean actual worker orchestration or database consumption ran.

## 3. Failed collection / precise environment issue

**RUNTIME-001 (P1 verification blocker, not a demonstrated production logic defect):** auth.py and auth_completeness collection import main→competitors→collectors→Amazon spider and fail because Scrapy is absent. Worker collection fails in worker.py on prometheus_client; analysis_worker.py→RAG pipeline→BM25Index on rank_bm25; discovery_worker.py→collectors on Scrapy. These packages are already declared in backend/src/ai/requirements.txt (rank-bm25 line 15, Scrapy line 107, prometheus-client line 114) and worker requirements where applicable. The intentionally narrow prior billing environment lacks them. No production import, test assertion or requirements file was patched to hide this. Provision the repository's declared full test/runtime environment, then rerun auth and workers; further missing/binary dependencies may surface and must remain visible.

## 4. Native obligations — all unexecuted

| Obligation | Status / required evidence |
|---|---|
| Native engine and isolation | Verify PG17 version, container image digest, dedicated loopback test DB, tmpfs/disposable volume and isolated credentials before DDL |
| Empty schema/migrations | Actual existing runner, baseline/schema and all migration files; record applied counts, errors and applied-file catalog |
| Repeat migrations | Existing runner repeat must be no-op; raw Task 6 SQL is not blindly executable twice |
| Populated historical upgrade | Historical report keys/usage, active/terminal subscriptions, paid invoices, tenant memberships preserved; repeat and lock/compatibility evidence |
| Effective catalogs / roles / RLS | pg_class/attribute/constraint/index/policy/proc/trigger, owners/ACLs, ceopro_app password login NOSUPERUSER/NOBYPASSRLS, tenant-context/wrong-tenant/bootstrap/service paths |
| 23 dynamic SQL obligations | Each [DYNAMIC_SQL_NATIVE_STATUS.csv](evidence/phase0v/DYNAMIC_SQL_NATIVE_STATUS.csv) row remains BLOCKED_VERIFY-001; source templates do not prove execution |
| Multi-session quotas/capacities | Independent native connections race for last report/quota/product/seat/source slot; inspect atomic successes/counters and capacity transaction contracts |
| Report idempotency | Same/different keys, actor/period/fingerprint conflicts, removed membership, canceled entitlement, once-only/stale/replayed refund receipts, HTTP exports |
| Stripe-state persistence | Actual signed-event logic plus explicit provider doubles: duplicate and reordered paid/failure invoices, reconciliation outage retry, stale old cancellation versus replacement; provider certification separate |
| Runtime and workers | Existing auth/entitlement/billing and applicable worker regressions with actual DB/roles; negative authorization and retry/reconciliation contracts |

Existing source tests cover some of these cases, but do not certify the whole matrix or all 23 dynamic SQL expansions. A bounded verification task must map remaining requested seat/source/product races to actual tests and report uncovered cases. Do not claim the existing integration_review runner automatically covers every obligation.

## 5. Blocking IDs and next action

1. **SOURCE-001 (P0 phase gate):** known correct uncommitted working bytes, but no clean team-reviewed post-Task-6 commit. Authorized team must review and supply its actual SHA/manifest; this task cannot create it.
2. **VERIFY-001 (P0 phase gate):** no isolated native PG17 runtime; every effective SQL/RLS/grant/concurrency/migration obligation above is NOT RUN.
3. **RUNTIME-001 (P1):** incomplete full-app auth/worker dependency environment caused five collection errors. Install declared runtime/test requirements in an isolated environment and rerun without production patches.
4. **PROVIDER-001 (release):** Stripe TEST, Shopify/Woo and approved AI-provider certification plus actual browser journeys NOT RUN. No credentials requested or used.
5. **DETAILS-001 (affected future behavior only):** material numeric/legal/contract subdecisions remain PENDING; 13 policy directions are already SELECTED. Do not ask for blanket policy reapproval.

Single next bounded task: **Phase 0V environment/baseline unblock and native foundation verification**, described in NEXT_IMPLEMENTATION_HANDOFF.md. No production corrective code task is justified by these infrastructure/collection failures; record any future native defect separately before seeking a narrowly scoped fix. **Not READY FOR PHASE 1A APPROVAL REVIEW.**
