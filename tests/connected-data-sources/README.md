# Connected Data Sources testing

This suite checks tenant-managed persistent connectors and their active-slot quota. It is separate from the Data Integration file-import tests in `tests/dataconnection/`.

## Verified quota contract

`data_integration` is the boolean permission to access persistent integrations. `connected_data_sources` is a separate lifetime `MAX` capacity. The current catalog sets Starter/Growth/Enterprise to 1/5/20.

The backend capacity resolver currently calculates:

```text
usage = COUNT(data_sources WHERE tenant_id = authenticated tenant AND is_active = true)
remaining = MAX(0, configured limit - usage)
```

The resolver counts every active `data_sources` row, regardless of `source_type`. Node's `countActivePersistentSources` helper filters to the six Node types. The AI service has a separate `OWN_SYSTEM_CONNECTOR` registration API, and competitor discovery also creates `WEB_SCRAPE` rows. The global resolver currently includes all of them, even though those are different source uses. Node's manual upload path writes `documents` as inactive; the AI extraction source helper inserts upload-source rows without setting `is_active`, so PostgreSQL's `true` default makes those active and quota-counted.

Source registration checks capacity in the service and then calls the repository to insert in a separate operation. The check and insert do not share a transaction, lock, or reservation. Concurrent registrations can race. Do not interpret a passing sequential quota test as proof of concurrency safety.

## Coverage map

| Area | Test file | What is covered |
|---|---|---|
| Catalog and pure capacity boundaries | `connected-data-sources-contract.test.mjs` | Boolean vs numeric features, lifetime reset, standard limits, 0/1/4/5/19/20 boundaries and unlimited policy |
| Source accounting and security contracts | `connected-data-sources-contract.test.mjs` | Tenant and active-row filtering, manual Node uploads, authenticated route, RLS policy, source validation architecture |
| Regression checks for known gaps | `connected-data-sources-contract.test.mjs` | Non-atomic Node quota/write, all-source-type counting, AI upload slots and AI capacity bypass, AI/Node source-type mismatch, unverified `verified` status, missing `updated_at`, missing quota UI, false-success actions, dropped website URL |
| Real API, browser, and database checks | `../e2e/connected-data-sources/connected-data-sources.spec.ts` | Plan-boundary registrations, SQL count vs API/UI, body tenant spoofing, Growth last-slot concurrency, and explicitly opted-in AI onboarding registration |
| Lifecycle and duplicate policy | Contract + Playwright blocked diagnostic | Current source routes have no activate/deactivate/delete API; source identity policy has no unique key or defined dedupe contract |

The regression checks intentionally fail while the named defect exists. Keep these failures visible; do not change application logic or mark them as skips to make the suite green.

## Tables and ownership

The quota source of truth is `data_sources`; registration is tenant-owned through `tenant_id`. The table has forced RLS in the baseline migration, guarded by `get_current_tenant()`. Source capacity itself is read from the effective subscription feature configuration through the existing feature usage repository. `ingestion_jobs` provides sync/import context, but a failed or absent job does not change `is_active` and must not release a slot.

Manual uploads are recorded as inactive `documents` rows by Node and should not consume persistent slots. The AI upload helper is a separate writer and is covered by a regression check. The AI team source writer and worker are not altered by this test package.

## Safe opt-in integration setup

The Playwright integration tests perform real POST requests and read actual PostgreSQL rows. They require disposable tenants already provisioned with the intended subscription/plan and owner membership. No production or development DB is accepted. The database name must include `test`, `testing`, `qa`, or `e2e`, and the connected DB role must not be a superuser or have `BYPASSRLS`.

Configure these environment variables in PowerShell before running the integration suite:

```powershell
$env:CONNECTED_DATA_SOURCES_TEST_DATABASE_URL = "postgresql://.../ceopro_connected_sources_test"
$env:CONNECTED_DATA_SOURCES_TEST_API_URL = "http://127.0.0.1:5000"
$env:CONNECTED_DATA_SOURCES_TEST_FIXTURES = '[{"plan":"Starter","tenantId":"<uuid>","userId":"<uuid>","accessToken":"<test-token>","expectedLimit":1},{"plan":"Growth","tenantId":"<uuid>","userId":"<uuid>","accessToken":"<test-token>","expectedLimit":5},{"plan":"Enterprise","tenantId":"<uuid>","userId":"<uuid>","accessToken":"<test-token>","expectedLimit":20}]'
$env:DASHBOARD_TEST_FRONTEND_URL = "http://127.0.0.1:5173"
```

Optional fixture fields: `foreignTenantId` enables the body tenant-spoof check; `dataIntegrationEnabled: false` enables the disabled-feature denial test. Set `expectedLimit: null` for an unlimited custom-plan fixture. Use separate isolated tenants, real access tokens for their owner users, and the actual effective limit (including custom plan overrides). The tests fill a finite-limit tenant to its expected limit with uniquely named website source rows, assert one more request is rejected, then mark only those uniquely prefixed test rows inactive. Unlimited tenants verify one registration succeeds. The database test role therefore needs the same tenant-scoped update permission used by the application. If fixture setup or safe cleanup is unavailable, tests remain BLOCKED/skipped with an annotation.

The AI onboarding registration test makes no external database connection and starts no sync. It sends a fixture-only configuration to the local AI registration endpoint. Run it only after confirming the AI process itself points to the same disposable CEOPRO test database:

```powershell
$env:CONNECTED_DATA_SOURCES_AI_BASE_URL = "http://127.0.0.1:8000"
$env:CONNECTED_DATA_SOURCES_AI_DB_TARGET = "DISPOSABLE_TEST_DATABASE"
```

The Growth concurrency case requires the Growth fixture to start with exactly four active rows and limit five. It sends two concurrent requests with distinct source identities, records both HTTP results, and independently queries final active rows. A setup mismatch is reported as BLOCKED rather than reshaping customer data.

## Commands

Run from `backend/`:

```powershell
npm run test:connected-data-sources
npm run test:connected-data-sources:contract
npm run test:connected-data-sources:e2e
npm run test:connected-data-sources:integration
npm run test:connected-data-sources:concurrency
npm run test:connected-data-sources:single -- -g "exact test name"
npm run test:connected-data-sources:headed
npm run test:connected-data-sources:ai
npm run test:connected-data-sources:report
npm run test:all-features
```

Reports reuse the existing Playwright configuration:

- HTML: `tests/reports/e2e/html/`
- JSON: `tests/reports/e2e/playwright-report.json`
- Structured diagnostics: `tests/reports/e2e/diagnostics.json`
- Failure screenshots, traces, and video: `tests/reports/e2e/artifacts/`

## Current implementation gaps

- Capacity check and insert are not atomic; concurrent last-slot requests may exceed the limit.
- The Node quota resolver counts all active `data_sources` rows, including AI-created `OWN_SYSTEM_CONNECTOR` and competitor discovery `WEB_SCRAPE` rows.
- AI file-upload bookkeeping creates active source rows and does not enforce `connected_data_sources`.
- AI database/API onboarding registration creates active `OWN_SYSTEM_CONNECTOR` rows without checking either catalog feature; the AI type is also absent from Node's six-type validator/list helper.
- The overview returns `dataStatus: "verified"` on source registration without verifying external connectivity.
- The Data Connections page has no visible numeric source limit/remaining-capacity value.
- Sync/reconnect preview methods resolve `{ ok: false }`, but the page displays a success notice after awaiting them.
- The frontend sends website `url`; the backend registration path does not persist or validate it.
- No persistent source activation/deactivation/delete endpoints or source identity/deduplication policy exist.
- `data_sources` has no `updated_at`; it cannot directly show the last lifecycle configuration change.
- Plan downgrade behavior and custom/unlimited capacity need a real subscription fixture; no lifecycle policy should be inferred by these tests.
- Live AI connector creation and provider sync need the AI worker and authorized fixture endpoints; no live connectors are called in ordinary tests.

## Existing-feature regression coverage

The all-feature runner invokes this contract and the existing feature E2E directories alongside Dashboard Analytics, Market Intelligence, Demand Prediction, Product Management, Competitor Management, and Data Integration. It does not replace those suites.

See [TEST_RESULTS.md](TEST_RESULTS.md) for this run's exact pass/fail/block counts and evidence-backed failures.
