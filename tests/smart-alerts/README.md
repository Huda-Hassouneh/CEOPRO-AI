# Smart Alerts QA package

Feature 14 (`system_alerts`) is covered here with tests and diagnostics only. No production application behavior was changed.

## Run

From the `backend/` directory, use PowerShell:

```powershell
./tests/runners/run-smart-alerts-tests.ps1
```

Run one layer with `-Mode Contract`, `-Mode Deterministic`, `-Mode Database`, `-Mode E2E`, `-Mode Headed`, or `-Mode Report`. `-Mode Single` runs the full Smart Alerts Playwright set. Equivalent npm commands are `test:smart-alerts`, `test:smart-alerts:contract`, `test:smart-alerts:deterministic`, `test:smart-alerts:database`, `test:smart-alerts:e2e`, and `test:smart-alerts:report`.

The Python deterministic runner uses the real price evaluator and threshold comparison without Scrapy or a database. Three assertions are deliberate source regression checks; the current code is expected to fail them until duplicate handling and previous-price integrity are implemented.

The database command delegates to the existing market scraper PostgreSQL/RLS integration suite. It requires all of the following before connecting or writing:

- `AI_TEST_DATABASE_URL` points to a dedicated database whose name contains a delimited `test`, `testing`, `qa`, or `e2e` marker.
- `AI_TEST_DATABASE_IDENTITY_VERIFIED=1` confirms the operator has checked the target service.
- `APP_DB_PASSWORD` is present for the restricted `ceopro_app` connection.
- Python has `pytest`, `psycopg2`, and Scrapy installed.

The test verifies the connected database name and rejects superuser or `BYPASSRLS` roles before seeding synthetic tenant-scoped rows. It does not exercise a Smart Alerts event-to-notification write because that integration is not implemented. Missing prerequisites produce `BLOCKED` (exit code 2); no database URL or password is printed.

The Playwright cases use a dedicated Smart Alerts reporter output. They are individually marked `BLOCKED` with the missing API or UI boundary. This is diagnostic coverage, not evidence of a live customer workflow.

## Current architecture verified

`ai/src/market_scraper/market_repository.py` creates `market_events` and `market_alert_events` from competitor-price changes. Its percentage is signed: `(new - old) / old * 100`; zero old price is suppressed. `scoring.alert_matches` applies strict `GT`/`LT` and inclusive `GTE`/`LTE` operators. Rules are selected by tenant, competitor, metric, and active state.

The previous-price query reads the latest `competitor_prices` record for a tenant/mapping but omits currency and does not constrain observations to the new event time. Alert events have no unique rule/event constraint, so retries can insert duplicates.

The tenant notification worker already has a durable outbox, per-tenant dedupe keys, recipient-specific receipts, conditional claims, retries, and one delivery transaction. However, its only event definition is `CUSTOM_PLAN_OFFER_READY`; there is no Smart Alerts producer or outbox handoff. Keep essential custom-plan billing notifications independent of Smart Alerts access.

`system_alerts` is a catalog boolean and lifetime feature, but Starter, Growth, and Enterprise do not currently grant it. The separate legacy `system_alerts` table is not the same as `market_alert_events`. No Smart Alerts rules API, acknowledge/resolve endpoint, settings flow, or alert preferences persistence was found. The notification inbox's read/archive receipt is not alert acknowledgement.

## Files and reports

- `smart-alerts-contract.test.mjs` checks plan/catalog boundaries, scraper formula and schema, notification worker/outbox behavior, missing integration, and frontend preference state.
- `ai/src/market_scraper/tests/test_smart_alerts.py` covers percentage examples, zero baselines, threshold boundaries, tenant rule filtering, duplicates, currency, and late-arriving observations.
- `tests/e2e/smart-alerts/smart-alerts-blocked.spec.ts` records currently unavailable customer-flow scenarios.
- `tests/reports/smart-alerts/` contains Playwright HTML, JSON, structured diagnostics, and run artifacts.
- `RESULTS.md` records actual outcomes from this run.
