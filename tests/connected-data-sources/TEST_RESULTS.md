# Connected Data Sources test results

Run on 2026-10-11 against the current CEOPRO source trees in this workspace. The work added tests and documentation only; it did not edit application or AI business logic.

## Feature contract

Command: `npm run test:connected-data-sources:contract`

| Result | Count |
|---|---:|
| Pass | 13 |
| Fail | 9 |
| Skip | 0 |

The 9 failures are the requested regression tests preserving issues found in the current implementation:

| Category | Evidence in current code |
|---|---|
| `SOURCE_TYPE_ACCOUNTING_MISMATCH` | `getCurrentCapacityUsage()` counts all active `data_sources`; it does not limit usage to persistent connector types. |
| `SOURCE_AUDIT_TIMESTAMP_MISSING` | Prisma `data_sources` has `created_at` and `last_synced_at`, but no `updated_at`. |
| `SOURCE_LIMIT_RACE_CONDITION` | The Node service reads capacity, then the repository performs a separate insert without a shared transaction, lock, or reservation. |
| `AI_UPLOAD_COUNTS_AS_CONNECTION` | AI extraction `resolve_or_create_data_source()` inserts upload rows without setting `is_active=false`; the schema default is true. |
| `AI_SOURCE_LIMIT_BYPASS` | AI `/onboarding/connect/database` and `/onboarding/connect/api` call a direct `OWN_SYSTEM_CONNECTOR` writer with no `data_integration` or `connected_data_sources` check. |
| `FALSE_SUCCESS_STATUS` | The overview returns `dataStatus: "verified"` even though registration does not test connectivity. |
| `FALSE_SUCCESS_UI` | `sync()` resolves `{ok:false}` and the page still displays a success notice. |
| `QUOTA_DISPLAY_MISSING` | The Connections page displays a connected-source count, but not the effective limit or remaining capacity. |
| `CONNECTOR_CONFIGURATION_MISMATCH` | The website form sends `url`, but Node validation/persistence do not save or validate it. |

Passing assertions verify the Starter/Growth/Enterprise limits (1/5/20), the separate lifetime boolean and MAX capacity features, capacity boundaries, unlimited custom MAX handling, active-source counting independent of sync health, Node manual upload exclusion, route authentication/tenant context, RLS policy, and the current absence of lifecycle routes and a defined duplicate identity key.

## Real API, browser, database, and AI checks

Command: `npm run test:connected-data-sources:e2e`

| Result | Count |
|---|---:|
| Pass | 0 |
| Fail | 0 |
| Blocked | 3 |

The three blocked scenarios are the Growth last-slot race, AI registration at capacity, and lifecycle/downgrade/duplicate behavior. No disposable database, fixture tenants, tokens, local API/frontend, or explicitly opted-in AI test service were configured. No database mutation or external connector call was made.

The E2E tests use the existing Playwright HTML/JSON/diagnostics reporters, failure screenshots and traces. Since each scenario was blocked before a browser/API operation, no screenshot or trace was produced.

## Type check

Command: `npx tsc --noEmit --pretty false`

Result: passed.

## Previous feature regressions

| Suite | Result |
|---|---|
| Dashboard contract | 1 passed, 0 failed |
| Market Intelligence contract | 2 passed, 4 failed: missing `market_intelligence`, `ai_pricing`, and `market_perception` entitlement checks on backend paths |
| Demand Prediction contract/client suites | 29 passed, 0 failed |
| Product Management contract | 11 passed, 0 failed |
| Competitor Management contract | 8 passed, 0 failed |
| Data Integration contract + existing focused tests | 24 passed, 0 failed |

The combined `npm run test:all-features` runner completed every suite and exited 1 because the Market Intelligence and Connected Data Sources contract suites have failures. Its Playwright diagnostic report contains 69 BLOCKED cases, 0 PASS, 0 FAIL, and 0 ERROR. The 69 are not passes; they reflect missing isolated tenant/database/service prerequisites across the existing feature suites.

## Confirmed catalog and schema facts

- Starter, Growth, and Enterprise source limits are 1, 5, and 20 in `src/config/production-plans.ts`.
- `data_integration` is boolean and `connected_data_sources` is a lifetime MAX capacity.
- The global MAX resolver counts active source rows only; failed or missing ingestion jobs do not release a slot.
- Node accepts Shopify, PostgreSQL, MySQL, SQL Server, GA4, and website source types. The AI registration API uses `OWN_SYSTEM_CONNECTOR`; AI extraction uses `<EXT>_UPLOAD`; competitor discovery creates `WEB_SCRAPE` sources.
- Node has no source activation/deactivation/delete routes. Plan downgrade behavior above the new quota and connector identity/deduplication rules are not defined in the inspected endpoints/schema.
