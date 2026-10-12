# Connected Data Sources testing

This suite checks tenant-managed persistent connectors and their active-slot quota. It is separate from the Data Integration file-import tests in `tests/dataconnection/`.

## Quota and lifecycle contract

`data_integration` is the boolean permission to access persistent integrations. `connected_data_sources` is a separate lifetime `MAX` capacity. The current catalog sets Starter/Growth/Enterprise to 1/5/20.

One shared source-type allow-list is used by Node usage, transactional source capacity, and source listing. Active `shopify`, `postgresql`, `mysql`, `sqlserver`, `ga4`, `website`, and AI `OWN_SYSTEM_CONNECTOR` rows consume slots. Inactive rows, manual-upload types, and unrelated collection types such as `WEB_SCRAPE` do not.

Node registration and reactivation acquire a tenant-scoped advisory lock and check quota in the same RLS-enabled transaction as the write. A database trigger takes the same lock and verifies both `data_integration` and `connected_data_sources` for all direct active-source inserts/reactivations, including AI service writes. A `NULL` custom-plan limit remains unlimited.

The resolver calculates:

```text
usage = COUNT(counted source types WHERE tenant_id = authenticated tenant AND is_active = true)
remaining = MAX(0, configured limit - usage)
```

At an over-limit downgrade, existing sources remain intact. New registrations and reactivation are blocked; users can pause or disconnect sources to restore capacity. Disconnect clears the vaulted credential field, marks the source disconnected, and retains its registration, jobs, staging, and business data.

## Coverage map

| Area | Test file | What is covered |
|---|---|---|
| Catalog and quota boundaries | `connected-data-sources-contract.test.mjs` | Boolean vs numeric features, lifetime reset, 1/5/20 plan limits, finite/unlimited behavior, tenant-scoped active usage, and shared source-type accounting |
| URL and identity validation | `source-url-normalization.test.mjs` | Website URL normalization and rejection of unsupported protocols, credentials, local hosts, and IP literals |
| Lifecycle and UI contracts | Backend contract plus frontend `connected-data-sources-feature.test.mjs` | Pause/reactivate/disconnect, credential clearing, historical-data retention, capacity display, entitlement gates, and English/Arabic copy |
| Real API, browser, and database checks | `../e2e/connected-data-sources/connected-data-sources.spec.ts` | Plan boundaries, usage display, tenant spoofing, last-slot concurrency, lifecycle, duplicate URL, direct DB trigger, and opt-in AI registration |

The frontend and deterministic contract tests run without a database. The Playwright tests require an isolated disposable database, real tenant fixtures, and a running API; direct AI tests are separately opt-in. Tests skipped because those prerequisites are absent are BLOCKED, not passing evidence.

## Tables and ownership

The quota source of truth is `data_sources`; registration is tenant-owned through `tenant_id`. The table has forced RLS in the baseline migration, guarded by `get_current_tenant()`. Source capacity itself is read from the effective subscription feature configuration through the existing feature usage repository. `ingestion_jobs` provides sync/import context, but a failed or absent job does not change `is_active` and must not release a slot.

Manual upload and AI upload bookkeeping source types are outside the connected-source allow-list. The database trigger protects the AI source writer without changing the AI repository.

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

## Remaining verification and integration work

- Run the opt-in API/PostgreSQL E2E suite after applying the migration to a disposable database; verify RLS, direct-writer checks, concurrent last-slot registration, lifecycle, and downgrade fixtures.
- Verify deployment of the shared database trigger before relying on it to protect AI direct-registration writes.
- Keep AI application behavior unchanged. The database rejects over-quota or feature-disabled direct writes, but the AI endpoint's user-facing error mapping remains owned by the AI team.
- Node website registration is still configuration metadata only; provider authentication and recurring sync remain Feature 8 work.
- Node registration does not yet populate the AI worker's collector key, approved policy, or encrypted credentials; the quota trigger does not make a source runnable by the AI worker.
- Schema has no `updated_at` for source lifecycle configuration changes; use job and creation timestamps only where their meaning is accurate.

## Existing-feature regression coverage

The all-feature runner invokes this contract and the existing feature E2E directories alongside Dashboard Analytics, Market Intelligence, Demand Prediction, Product Management, Competitor Management, and Data Integration. It does not replace those suites.

See [TEST_RESULTS.md](TEST_RESULTS.md) for this run's exact pass/fail/block counts and evidence-backed failures.
