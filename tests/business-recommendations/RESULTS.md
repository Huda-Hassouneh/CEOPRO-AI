# Business Recommendations test results

Run date: 2026-10-11. Scope: source-level and deterministic QA; no production logic was modified.

## Directly executed checks

| Check | Result | Detail |
|---|---|---|
| Node catalog/plan/architecture contract | **PASS** | 8 passed, 0 failed. |
| Deterministic AI rule and source audit | **FAIL (expected regression findings)** | 49 checks: 43 passed, 6 failed against current source. See findings below. |
| Python pytest unit suite | **BLOCKED** | `pytest` is not installed in the selected Python runtime. |
| AI PostgreSQL integration/RLS suite | **BLOCKED** | `pytest` unavailable; no `AI_TEST_DATABASE_URL` configured. No database connection was attempted. |
| Customer-facing Playwright scenarios | **BLOCKED** | 18 scenarios skipped with explicit diagnostic categories because the Node recommendation route and connected UI do not exist. |
| Optional live AI endpoint probe | **BLOCKED** | 1 skipped; endpoint opt-in and verified test tenant/database were not configured. |
| Python syntax compilation | **PASS** | `compileall` succeeded for all changed Python test modules. |
| Full existing feature regression runner | **FAIL** | Seven suite groups reported failures: Market Intelligence contract; Connected Data Sources contract/quota; Document Extraction; Document Storage; RAG Assistant source regressions; Business Recommendations deterministic regressions; Business Recommendations Python/API suite. This run is not a clean baseline. |

The six deterministic failures are source regression checks, not defects introduced by this test package:

1. Price-gap query does not require comparable currency.
2. Price-gap query does not exclude inactive/untracked mappings.
3. Price-gap query does not exclude unavailable observations.
4. Sales trend includes unpaid/cancelled invoice states.
5. Sales trend has no current-time upper bound for future-dated invoices.
6. Latest forecast selection does not exclude expired target dates.

The full feature regression result records simultaneous failures in existing feature suites. Because there was no clean pre-change run in this session, this report does not attribute those failures to this package.

## Direct suite status versus orchestration

The feature orchestration script writes `tests/reports/business-recommendations/run-summary.json`. In this restricted Work Mode runtime, nested `spawnSync` calls may return `EPERM`; such orchestrated suites are labeled `BLOCKED`. Use the direct npm commands above for the authoritative per-suite output in this environment. The individual commands listed in the table were run directly.
