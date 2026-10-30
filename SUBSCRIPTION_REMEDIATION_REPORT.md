# Subscription remediation report — Task 6

**Date:** 20 October 2026. **Destination:** main repository used for Tasks 1–5. **Result:** production fixes implemented; **140 passed, 0 failed, 10 skipped** in the completed recovered-code run. **Independent verification: ready. Production/release approval: pending native PostgreSQL and provider verification.**

This report supersedes the earlier verification-only handoffs for the defects addressed below. It does not claim completion of real concurrency verification: requirement 5 remains partially blocked by the available environment.

## 1. Scope, repository identity and permissions

Main's actual backend is Python/FastAPI, although the task says Node.js. The updated permission to modify narrowly scoped commercial code under `backend/src/ai/**` was applied to billing, quota enforcement and route access only. No competing Node service, subscription schema, entitlement evaluator or billing owner was introduced.

Target input: `main-repo.zip`, SHA-256 `b3571d2f7c9deff451c723711c304c255cd0758d7ac553aad32d3782afc1fa54`, 1,277 original files. Read-only reference: `my-version.zip`, SHA-256 `c8a3bf461a36e61cba9640d6c791545349db5a3abee09425056b21b02a407788`, 2,839 original files. These are the Task 1–5 inputs, not an assumption about any unseen newer branch or archive.

An interrupted working directory was unavailable on continuation. Main and the saved Task 5 verification bundle were restored; the previously developed fixes were recovered and the final test run was executed against that recovered code. Earlier test counts were not substituted for this run.

## 2. Root causes and production changes

### 2.1 Delayed invoice failure overwrote confirmed payment

**Root cause:** `_handle_locked` reconciled the subscription but trusted the event's stale invoice snapshot. `record_payment` then unconditionally updated the invoice-ID row to the incoming failed status. Event-ID idempotency could not order distinct events for the same invoice.

**Files:** `backend/src/ai/billing/webhooks.py`, `backend/src/ai/billing/store.py`.

**Fix:** acquire a transaction advisory lock per invoice before retrieving its current state through the existing `stripe_api.retrieve_invoice`. Validate invoice/subscription/customer identity. A currently paid invoice is stored as succeeded even when the triggering event was an older failure. Provider reconciliation failures use the existing retryable webhook path: rollback domain writes, retain an unprocessed/error event, return 500 and allow retry. Successful same-event redelivery remains a duplicate.

Subscription snapshots are also serialized per subscription ID before retrieval. The existing session event lock and raw-body Stripe signature verification remain in place. A defensive store upsert prevents an internal failed payment write from regressing an existing succeeded row or modifying another tenant's row.

Locks are held through the existing persistence transaction, with invoice → subscription → tenant ordering. No new webhook endpoint or provider client was introduced. Refund handling is not implemented by this patch; refunds are separate from an invoice's paid status.

### 2.2 Old subscription cancellation revoked a replacement subscription

**Root cause:** the assignment upsert allowed terminal state whenever the current assignment had `source='stripe'`, without establishing which subscription was in force. An old canceled subscription's later event therefore replaced a newer active tenant assignment.

**File:** `backend/src/ai/billing/store.py::apply_subscription`, with synchronization in `billing/webhooks.py`.

**Fix:** serialize assignment writes for each tenant using a transaction advisory lock. Preserve the incoming subscription's history, but skip its assignment write if another current subscription exists for that tenant. Subscription-ID upserts cannot change an object bound to another tenant; provider customer mappings are checked for tenant conflicts before application. Existing mappings and history are retained.

The current-status set and existing single-current-subscription invariant remain main-owned. If Stripe actually contains two competing live subscriptions, an existing uniqueness/conflict failure may still require reconciliation; this patch does not silently pick an arbitrary winner or erase either provider object. Simultaneous distinct-subscription transitions still require native multi-session verification.

### 2.3 Report keys bypassed cancellation and period accounting

**Root cause:** `reserve_request` returned the duplicate sentinel before active-status checks, looked up keys without the period, and did not validate a stored actor/request binding. The old primary key also excluded the period. Release calls could decrement usage repeatedly or target a replacement attempt that reused a released key.

**Files:** `backend/src/ai/core/usage.py`, `backend/src/ai/routers/reports.py`, and new migration `backend/src/infrastructure/database/migrations/20261024000000_report_request_identity.sql`.

**Fixes:**

- Under tenant/feature transaction locks, resolve the current plan and require active/trialing access **before** any duplicate return. A zero/excluded report allowance cannot be bypassed by an old key.
- Recheck active tenant membership for supplied actors. HTTP exports always supply the authenticated user; existing trusted service callers may still omit an actor. A key bound to a different actor is rejected.
- Scope key identity to `(tenant_id, feature_code, period_start, idempotency_key)`. Preserve historical rows and usage; a new period can reuse a key and be counted normally.
- Bind HTTP requests to a SHA-256 fingerprint of report type, format, language and date parameters. Identical authorized retries count once. Reusing the key with changed parameters returns 409 rather than another free export.
- Add a generated request receipt UUID. Failure refunds delete the matching period/receipt first and decrement usage only when that deletion succeeds. Repeated or delayed refunds cannot decrement twice or refund a replacement request.
- Mark authorized replays. An original failure cannot refund a replay that may have succeeded. This is conservative accounting: when a key has been replayed and all deliveries subsequently fail, the unit remains counted because the original callback alone cannot establish that no usable result reached a caller. Such cases require operator review; no twice-charging is introduced.
- Reject boolean, fractional, nonfinite and nonpositive reservation amounts before SQL. Existing conditional counter upserts remain the quota authority.

Existing URL, request fields, successful report responses, file download behavior and 402 body remain unchanged. New 409 conflicts are intentional security corrections. Historical current-period keys without a verifiable fingerprint fail closed with 409; retry with a **new** key. Pre-deployment in-flight receipts without the new UUID cannot refund a later request and remain counted for review. These rollout effects must not be mistaken for lost history.

### 2.4 Forecast generation alias lacked the module dependency

**Root cause:** `/forecasting/*` had the existing demand-prediction dependency, while `POST /dashboard/products/{product_id}/forecast` directly called the forecast pipeline without it.

**File:** `backend/src/ai/routers/dashboard.py`.

**Fix:** add `dependencies=[requires(usage.DEMAND_PREDICTION)]` to that specific route and import the existing helper/feature constant. Authentication, tenant context, URL, parameters, handler body, result and inference call are preserved. No dashboard metric or model calculation changed.

### 2.5 Concurrency safety and verification boundary

The existing conditional SQL counter upsert was retained. Report-key creation/replay/release is serialized per tenant/feature; assignment-sensitive reservation also shares the tenant commercial lock with webhook assignment updates. Refund receipt matching closes repeated/stale release errors, and replay marking prevents refunding an allowance authorized for another delivery.

**Native concurrency verification could not be executed here.** `postgres`, `initdb`, `pg_ctl` and Docker are absent. The container has a single UID mapping and denied creating a non-root UID namespace (`Operation not permitted`). No OS/root-check bypass was used to manufacture a native test result.

Two new native tests issue twelve simultaneous **actual HTTP exports with real PostgreSQL connections**: distinct keys compete for two remaining units, and identical keys must all reuse one unit. Existing native last-unit reservation and duplicate-webhook race tests remain present. These are not mocked concurrency tests, but they are **unexecuted** in this environment. SQL correctness under isolated sequential execution does not prove race safety.

## 3. Exact production files

Modified original files — only these five:

1. `backend/src/ai/billing/webhooks.py` — invoice reconciliation, serialization and identity validation.
2. `backend/src/ai/billing/store.py` — current-subscription assignment safety and monotonic paid history.
3. `backend/src/ai/core/usage.py` — reservation validation, replay access/identity checks and safe refunds.
4. `backend/src/ai/routers/reports.py` — canonical report parameter fingerprint passed to the same accounting service.
5. `backend/src/ai/routers/dashboard.py` — the forecast route dependency/imports only.

New production migration:

6. `backend/src/infrastructure/database/migrations/20261024000000_report_request_identity.sql` — period-aware key primary key, nullable request fingerprint, replay flag and UUID receipt. Existing ownership, grants, RLS and FORCE RLS are retained. No Prisma changes or historical migration edits.

No production dependency, credentials, environment values, frontend request fields or AI algorithm contracts changed.

## 4. Tests added and necessary test maintenance

New files under `backend/tests/remediation/`:

- `__init__.py`, `conftest.py`: reuse existing guarded real-SQL/runtime-role fixtures; no duplicate authorization or persistence layer.
- `test_commercial_boundaries.py`: reconciliation outage/retry/duplicate behavior, invoice customer and subscription identity rejection, monotonic payment storage, changed report parameters, removed and cross-tenant actors, same-tenant actor mismatch, repeat/stale/replayed refunds, period-specific release, legacy key conflict and invalid amounts.
- `test_forecast_gate.py`: exact source-loaded route/decorator through FastAPI, testing inactive, missing-module and included access. Real entitlement SQL is used; inference and product lookup are explicit boundary doubles. This is **not** full model-server execution.
- `test_migration_upgrade.py`: execute the actual new SQL against the historical key-table definition in a temporary schema, preserving a historical row, RLS/FORCE RLS and grants, and allowing the same key in a new period. Roll back the test schema.
- `test_native_concurrency.py`: native-only concurrent HTTP tests described above.

Modified verification files:

- `backend/tests/billing/test_database.py`: its failure-then-success fixture now supplies the authoritative invoice retrieval double and actual `open`/`paid` states. Its assertions and the previously failing delayed-event regression are retained. Import formatting was normalized.
- `backend/scripts/integration_review.py`: include `tests/remediation` in the guarded combined run.

The pre-existing regression tests for all nine Task 5 failures were rerun and pass. They were not skipped, weakened or changed to accept the incorrect states.

## 5. Executed tests and actual results

Final recovered-code run: **150 tests, 140 passed, 0 failures/errors, 10 skipped**. Pytest exit code 0. One nonfatal FastAPI/Starlette test-client deprecation warning.

| Suite | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Existing verification `tests/billing` | 61 | 0 | 2 |
| Existing verification `tests/entitlements` | 42 | 0 | 1 |
| Existing `tests/integration_review` | 15 | 0 | 5 |
| New `tests/remediation` | 20 | 0 | 2 |
| Unchanged main billing/frontend contract consistency tests | 2 | 0 | 0 |
| **Total** | **140** | **0** | **10** |

Environment: Python 3.12.14, pytest 9.1.1, stripe-python 15.6.1, FastAPI 0.150.0, psycopg2-binary 2.9.13 and a disposable PGlite PostgreSQL 17.5 engine. Test dependencies were installed outside the repository; production requirements were not modified.

Executed against the actual baseline and migration runner: **78 migrations applied on fresh setup, zero on repeat**. Existing repeat-run and failure-rollback tests passed. Historical-table forward upgrade preservation passed. No existing user database was migrated or reset.

Actual runtime-role SQL/RLS tests use `SET ROLE ceopro_app`, assert no superuser/BYPASSRLS, and reject other-tenant reads/writes. Main's production defaults were enforced for the run: `UNASSIGNED_PLAN_ACCESS=none`, `KEEL_TEST_DISABLE_METERING=0`. No default-plan or credit-bypass test setting was used to turn failures green.

Stripe network responses are explicit test doubles; the actual SDK verifies signed event bodies. Generated fixture tenants/private prices/counters exist only in the disposable test database. No reference/demo seeder or fabricated AI results were inserted into production logic.

Full Ruff checks of new/maintained test tooling passed; syntax/undefined-code checks of the five modified production files passed. Broad reformatting of existing production files was avoided.

Evidence: `docs/remediation/test_run.log`, `test_results.xml`, `source_integrity.json`, `native_capability.json`.

### Skipped or otherwise unverified

Ten explicit final skips: native concurrent duplicate webhooks (1), native runtime-role password login (1), native last-unit quota race (1), three staff-mutation HTTP paths that hold two connections (3), full HTTP upgrade/downgrade (2), new concurrent HTTP quota cases (2). PGlite's multiplexed backend is not a substitute for independent native PostgreSQL sessions. Native tests run by default when `BILLING_TEST_ENGINE` is unset.

Also unverified: real Stripe TEST network delivery/Checkout/Test Clock/SCA, full model-server startup, Redis/network boundaries, live populated deployment upgrade, multi-process cache invalidation and full original backend/model suites. Importing the full dashboard module hit unavailable/incompatible AI binary dependencies during exploration; model code was not modified to work around that. The exact-handler gate test avoids loading those binaries and is explicitly isolated.

## 6. Migration/application procedure

The new SQL must be deployed with the new report accounting code. Back up and rehearse on a disposable restore first. Quiesce report writers/API replicas during the schema/code switch; do not run old and new accounting implementations concurrently. Applying the SQL alone does not fix old lookups. The new columns/UUID default and primary-key replacement acquire table locks; size/lock duration on a real populated deployment is not measured here.

From main's repository root, after extracting the ZIP there:

```powershell
Set-Location .\backend
py -3.12 -m venv .venv-remediation
$testPython = Join-Path $PWD '.venv-remediation\Scripts\python.exe'
& $testPython -m pip install -r tests\billing\requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Test dependencies failed.' }
```

Provision the **dedicated disposable native PostgreSQL** cluster defined in `tests/billing/docker-compose.yml`; it must not be KEEL_DEV or a production database. Configure its Compose password/port locally, then run:

```powershell
$env:BILLING_TEST_DATABASE_URL = Read-Host 'DSN of disposable localhost keel_billing_test database'
& $testPython -c 'import os; from scripts.billing_verification import validate_test_environment; validate_test_environment(dict(os.environ), database=True)'
if ($LASTEXITCODE -ne 0) { throw 'Test database guard rejected configuration.' }

$savedUrl = $env:DATABASE_URL
$savedPassword = $env:APP_DB_PASSWORD
try {
    $env:DATABASE_URL = $env:BILLING_TEST_DATABASE_URL
    $env:APP_DB_PASSWORD = [Guid]::NewGuid().ToString('N') + 'aA9!'
    & $testPython -m scripts.apply_migrations
    if ($LASTEXITCODE -ne 0) { throw 'Disposable database migrations failed.' }
    Remove-Item Env:BILLING_TEST_ENGINE -ErrorAction SilentlyContinue
    & $testPython -m scripts.integration_review --database --junitxml remediation-native.xml
    if ($LASTEXITCODE -ne 0) { throw 'Native verification failed; inspect the test report.' }
} finally {
    if ($null -eq $savedUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
    else { $env:DATABASE_URL = $savedUrl }
    if ($null -eq $savedPassword) { Remove-Item Env:APP_DB_PASSWORD -ErrorAction SilentlyContinue }
    else { $env:APP_DB_PASSWORD = $savedPassword }
}
```

The generated password is only for the disposable test role. The guard refuses application database names/remote DSNs and live Stripe keys. Do not paste secrets into conversation. Existing main migrations require their documented schema-owner/role-management privileges; the application continues to use its restricted role.

These native PowerShell commands are provided for independent verification and were **not** run here. Once native/staging checks are approved, the actual application uses its existing environment and migration command (`python -m scripts.apply_migrations`) under its migration role. No command in this task applied changes to the user's running database.

### Rollback

If migration fails, the existing runner rolls back the file and does not mark it successful. Before activation, keep the prior deployment and restore the tested backup if needed. After period-specific keys exist, do not delete history or force the old primary key back into place. Disable/quiesce report exports and repair forward. Old source is not a safe rollback for the key bypass merely because the new schema is additive. New receipt-less in-flight failures need manual accounting review; automatic refunds deliberately fail closed.

## 7. Protected-source integrity

Byte comparisons against the original archives found exactly the five permitted commercial Python files changed. All other original main files—including frontend, models, workers, inference pipelines, AI algorithm modules, historical migrations and Git metadata—remain unchanged. All **2,839** reference files remain unchanged. The forecast handler's body and arguments also match the original AST exactly; only imports/decorator access metadata changed.

The handoff contains updated files at main-root-relative paths, tests/tooling and this report/evidence. It is not a whole replacement repository and does not contain credentials, dependencies, model binaries or Git metadata.

## 8. Remaining blockers and readiness

**Ready for independent verification of these production fixes: YES.** The earlier protected-source blocker no longer prevents the targeted changes; they are implemented and their available regressions pass.

**Task 6 requirement 5 fully verified: NO.** Native concurrent requests were not executed. Do not describe the skipped cases as passes or this isolated run as proof of race-free production behavior. Independent review must run the native tests and resolve any failures.

**Ready for unconditional merge/deployment: NOT YET.** Complete native checks, real Stripe TEST smoke tests, populated-upgrade rehearsal and code review first. Earlier findings outside this targeted task—pricing/retry policy, sentiment accounting, worker execution-time checks and direct hosted AI/Redis security boundaries—remain outside this patch. No claim of universal enforcement across those services is made.

No commit, push, merge or deployment was performed.
