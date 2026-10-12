# Connected Data Sources test results

Run on 2026-10-12 against the latest frontend and backend snapshots in this workspace. AI source code was neither included nor modified; the contract suite verifies the database boundary without requiring an AI checkout.

## Backend contract and URL tests

| Test | Result |
|---|---:|
| Connected Data Sources contract checks | 26 passed, 0 failed |
| Website source URL normalization checks | Passed |

Checks cover the Starter/Growth/Enterprise 1/5/20 limits, custom unlimited limits, shared source-type accounting, Node transaction locking, the shared database quota trigger, tenant context, pause/reactivate/disconnect behavior, credential clearing, downgrade visibility, and source URL validation.

The tests were run with Node's built-in TypeScript stripping because package dependencies are not installed in this workspace. `npm ci --offline` could not complete because the required `zod` package was not present in the local npm cache.

## Frontend tests

| Test | Result |
|---|---:|
| Connected-source UI contract | Passed |
| API error localization regression | Passed |

These tests validate source-capacity display, source entitlement gates, manual-upload access outside connector-slot gating, disconnect confirmation and API use, and English/Arabic copy.

## Real API, database, and UI E2E

The Playwright E2E suite now contains tests for plan capacity, concurrent final-slot requests, source pause/reactivation/disconnect, duplicate website URLs, disabled `data_integration`, direct database writes, tenant isolation, and optional AI registration. It was not run here: no Node dependencies, running API/frontend, or disposable RLS database and tenant fixtures are configured. Those results remain **BLOCKED**, not passed.

The database trigger migration has not been applied or exercised against PostgreSQL in this workspace. Deployment and database-level concurrency/RLS behavior still need the disposable-database run.

## Remaining Feature 9 boundary

- The database migration protects direct AI source writes without changing AI code. The AI endpoint may return a generic server error for database quota rejections until its team maps the database error to a user-facing response.
- Quota enforcement does not connect Node-created sources to AI collector keys, provider credentials, approvals, or scheduled synchronization. Those are Feature 8 integration tasks.
- Existing sources are kept active through plan downgrades; adding/reactivating is blocked, and pause/disconnect remains available to release slots.
