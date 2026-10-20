> Current Phase 1A update (2026-10-20): the owner explicitly authorized bounded production authentication/platform implementation in an isolated copy. Historical Phase 0/0R/0V statements about missing implementation permission describe their original stage. Current source, limits and actual tests: [PHASE1A_IMPLEMENTATION_REPORT.md](PHASE1A_IMPLEMENTATION_REPORT.md). Native verification and production release remain blocked.

# Source baselines and provenance

## Frozen inputs

| Input | SHA-256 |
|---|---|
| `Task 6 final report.md` | `fbce3f8801ca6477569c7cd5c14cf36ebd257138ee63778c96d9bd839088648a` |
| `my-version.zip` | `c8a3bf461a36e61cba9640d6c791545349db5a3abee09425056b21b02a407788` |
| `main-repo.zip` | `873cc27c3d98a9a061a843d4a63948ac7db178555c4c8757fbee31c59b2285e7` |
| `KEEL_UNIFIED_PYTHON_INTEGRATION_WORK_MASTER_PROMPT.md` | `2f2251aa34a4cfdc1744caf95e3fa17c97601d8a141ebeeb775b3c27adf49446` |
| `KEEL_UNIFIED_FILE_CHANGE_LEDGER_TEMPLATE.md` | `d58bcc0ad394da60d0a18a6322c8efa0e685587c5751d764b56f210134325ffc` |

All source citations are relative to `keel/` (Node) or `CEOPRO-AI/` (Python), at the supplied content hashes in `evidence/SUPPLIED_CONTENT_HASHES.json`. That manifest records 2,839 Node files and 1,283 Python non-Git files before this task, not a guessed remote HEAD. ZIP paths were `my-version.zip:keel/` and `main-repo.zip:main-repo/CEOPRO-AI/`.

Node has no root Git metadata in the supplied archive; the read-only byte manifest is its identity. Python branch `main`, HEAD `1de393c77dfc6db9d8722d8a611d2384d64d12c0`. Remote branch freshness cannot be established from an archive. No checkout/reset/commit was used to disguise incoming changes.

## Task 6 presence versus completion

Supplied `Task 6 final report.md`, Python `SUBSCRIPTION_REMEDIATION_REPORT.md`, `SUBSCRIPTION_REMEDIATION.patch`, `docs/remediation/{manifest,source_integrity,test_run,test_results,native_capability}` are evidence. Source inspection confirms:

| Repair | Current source | Verification boundary |
|---|---|---|
| Paid invoice cannot regress from late failure | billing/webhooks.py `_handle_locked`, billing/store.py `record_payment` | retrieve_invoice plus per-invoice/subscription/tenant locks present; native reordered races unrun here |
| Old canceled subscription cannot replace newer assignment | billing/store.py `apply_subscription`, webhooks.py `sync_subscription` | identity guard present; competing live subscriptions still reconciliation case |
| Report replay cannot bypass canceled plan | core/usage.py `reserve_request` | access/membership precedes replay return |
| Same key new billing period | `20261024000000_report_request_identity.sql` | period included in key; migration application not verified here |
| Request/actor binding and safe release | routers/reports.py fingerprint; usage.py `release_request` | receipt/period/fingerprint/replay safeguards present |
| Forecast alias module dependency | routers/dashboard.py product forecast decorator | demand_prediction dependency present |
| Invalid quota reservation amount | usage.py `reserve`, `reserve_request` | Boolean/nonpositive/noninteger values rejected |

The archive is not clean: widespread CRLF content differences and Task 6 modifications are present. `git diff --ignore-space-at-eol --name-only` reduces tracked semantic differences to `billing/store.py`, `billing/webhooks.py`, `core/usage.py`, `routers/dashboard.py`, `routers/reports.py`, under `backend/src/ai/`. Untracked migration/tests/reports are incoming content. Treat them as **pre-existing**; they are not this phase's additions and must not be attributed to the Phase 0 ledger.

**SOURCE-001 blocker:** user/team must establish a reviewed post-Task-6 clean commit that contains the intended five patches, new migration and tests, with full diff/test evidence. Do not run overlapping implementation on this dirty checkout. Then compare it byte-for-byte with this snapshot and regenerate affected traces if different.

## Environment and baseline

Python 3.12.14; Node v24.19.0. Verification dependencies installed in a scratch-only venv: FastAPI 0.150.0, Stripe SDK 15.6.1, psycopg2-binary 2.9.13, pytest 9.1.1, Redis client 8.1.0. Production requirements were not changed. Project RUNNING_LOCALLY.md requests Python 3.11 and Node 20+; validate release runtime independently.

No postgres/initdb/pg_ctl/Docker executable was found on PATH or the inspected `/usr` and `/opt` trees. No native server, Redis server, provider test account or model server was started; no user's/shared database was used. Previous Task 6 used PGlite PostgreSQL 17.5; that is not native concurrent proof.

Recorded commands/results are in TEST_EVIDENCE.md. Repository startup authority: `keel`, RUNNING_LOCALLY.md, backend/scripts/apply_migrations.py, Docker/compose configuration, src/ai/main.py. Secrets/env **names only** are indexed; no credentials included.

## Content integrity

`evidence/SOURCE_INTEGRITY_FINAL.json` records after-task byte comparison to the frozen pre-task manifest. Only `docs/keel-integration/**` is delivered. Dependency caches/node_modules/build outputs are disposable verification outputs and excluded from the delivered diff. Existing source, migrations, configuration, Git metadata and Node must remain byte-identical.


## Phase 0R refinement

See [PHASE0R_README.md](PHASE0R_README.md), [SOURCE_SNAPSHOT_RECONCILIATION.md](SOURCE_SNAPSHOT_RECONCILIATION.md), [SCHEMA_VERIFICATION.md](SCHEMA_VERIFICATION.md) and [DOMAIN_READINESS.md](DOMAIN_READINESS.md). Exact capability source roots, real schema lineage and thirteen concrete owner questions have been refined; no implementation or approval occurred. Earlier 56-pass/94-skip backend and 90-pass frontend/build logs are prior Phase 0 evidence, not rerun Phase 0R acceptance. SOURCE-001 and VERIFY-001 remain blocked. Raw lexical DB evidence is nonauthoritative.
