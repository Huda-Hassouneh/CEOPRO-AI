# Smart Alerts QA results

Run date: 2026-10-11 (UTC)

| Suite | Outcome | Details |
|---|---|---|
| Node source contracts | PASS | 15 checks passed after fixing a test matcher to reflect the worker's multiline call formatting. |
| AI deterministic calculations | FAIL: 3 regressions | 10 checks ran: 7 passed, 3 failed. Price deltas, zero baseline, tenant-scoped rule selection, and all four threshold operators passed. Failures: same market event is inserted repeatedly; previous-price lookup omits currency; previous-price lookup has no event-time upper bound. |
| PostgreSQL/RLS integration | BLOCKED | No `AI_TEST_DATABASE_URL`, verified database identity, app password, or configured test DB prerequisites were available. The runner stopped before connecting. |
| Smart Alerts Playwright diagnostics | BLOCKED | 10 cases were recorded as skipped/blocked because the rule API, event-to-outbox producer, delivery integration, alert lifecycle API, preferences, or customer page is absent. This is not reported as a passing E2E workflow. |
| Existing tenant notification regression suite | PASS | 4 tests passed. |
| Existing platform notification regression suite | PASS | 4 tests passed. |

No production database was contacted. The guarded database runner printed only missing prerequisite names and exited before starting pytest. No product logic was edited.

The deterministic failures are source-level expected regressions, not environment failures. The blocked database and browser scenarios remain unverified until the missing safe test environment and application paths exist.
