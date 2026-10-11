# Competitor Management Testing

## Run

From `backend/` in Windows PowerShell:

```powershell
npm run test:competitor-management:contract
npm run test:competitor-management:e2e
npm run test:competitor-management:headed
npm run test:competitor-management:live-ai
npm run test:competitor-management:single -- tests/e2e/competitor-management/competitor-management.spec.ts -g "owner creates"
npm run test:e2e:report
```

`test:competitor-management` runs contracts then Playwright. `integration` aliases source/schema contracts because no separately configured database suite is available. All four previous feature suites remain included in `test:feature-e2e` and `test:all-features`.

## Verified ownership map

| UI → API → persistence | Current behavior |
| --- | --- |
| Competitor list → `GET /competitors` → `tenant_competitors` joined to `global_competitors` | Authenticated and tenant-scoped; active tracked rows only. Search and industry filtering are client-side. Industry options are fixed; the adjacent Filter button has no handler. |
| Add form → intended `POST /competitors` → global identity plus tenant link | Backend endpoint exists. The rendered Add Competitor page calls `addPreviewCompetitor(values)` and navigates away; it does not call the real mutation/API. Form requires name and website in the browser, while backend service requires only name. |
| Profile → `GET /competitors/:id` → tenant link, product mappings, available price rows | Query is tenant-scoped and only returns mapped products with available observations. Activity is derived from adjacent saved prices. Metrics/strengths/weaknesses/presence are placeholders. |

Backend create reuses a global row by **exact name** and ignores website/industry values when that name already exists. New rows are global and tenant links are upserted as tracked. This differs from AI discovery, which has website identity keys and private identity paths. No edit/untrack/reactivate endpoints exist in the Node router.

Growth catalog values are 10 tracked competitors and 1,440-minute monitoring metadata; Enterprise values are 50 and 360 minutes. The competitor API service/repository does not invoke feature access or `tracked_competitors` capacity checks. Catalog configuration alone does not demonstrate backend enforcement, concurrency safety, job scheduling, or successful scrape cadence.

## AI and ingestion boundary

AI FastAPI `/extraction/upload` promotes created products and publishes `market.discovery.requested`. The discovery worker runs product/domain discovery. Collection is queued only when the discovered result is already `ALLOWED`; it does not approve unreviewed sources. CEOPRO Node's hosted extraction controller does not publish this event in its normal upload flow. Scheduled connector sync paths stage/process records and are distinct from the FastAPI upload-and-promotion flow.

Scraping was not run. There is no configured disposable test tenant, verified runtime identity, Redis worker environment, authorized test source, or cleanup contract. All operational E2E scenarios are therefore explicitly `BLOCKED`, not passed. The Playwright report stores structured annotations in `tests/reports/e2e/diagnostics.json`; HTML and JSON reports use the shared Playwright configuration. Blocked tests do not produce screenshots/traces.

## Contract and E2E coverage

The source/schema contract tests verify API routes, frontend wiring, identity behavior, plan values, forced RLS/composite tenant keys, profile price shaping, and the AI discovery event boundary. Playwright lists persistence, validation, duplicate identity, tenant isolation, plan limits/concurrency, lifecycle, profile freshness/currency, mappings, placeholders, normal ingestion trigger, and opt-in AI discovery. They remain blocked until real controlled fixtures and the required application features exist; no competitor responses are mocked.

| Test area | UI | API | DB/schema | AI/worker | Result |
| --- | --- | --- | --- | --- | --- |
| Add/persist competitor | Preview state | Create exists | Relationship write exists | N/A | Contract finding; E2E blocked |
| Listing/profile | Real API hooks | Tenant scoped | Forced RLS and keys | Producer outside API | Contracts pass; E2E blocked |
| Duplicate identity | Form preview | Exact-name global reuse | AI website-key path differs | Discovery identity exists | Contract finding; E2E blocked |
| Plan access/capacity | FeatureGate wrapper | No server gate found | Catalog limits only | N/A | Contract finding; E2E blocked |
| Track/untrack lifecycle | No complete controls | Create/list/profile only | Link supports tracking state | N/A | E2E blocked |
| Discovery/source policy | N/A | Upload paths differ | Candidate/mapping persistence | Event and ALLOWED policy gate | Contract passes; live E2E blocked |
| Pricing/freshness/mapping | Profile view | Latest available price + adjacent changes | Mapping/price tables | Scraper producer | Contract finding; E2E blocked |
| Cross-tenant isolation | N/A | Tenant filters | Forced RLS | Worker uses tenant context | Schema/source contract only; DB run blocked |

## Safety

The tests do not create database fixtures, contact AI services, use Redis, or issue live scraping requests. Before enabling database-mutating E2E, configure an explicitly disposable migrated database, two verified non-superuser tenant memberships, independently owned fixture IDs, and bounded cleanup. Never treat a source-contract assertion as evidence of a live worker run or actual RLS behavior.

## Current run record

Execution record (2026-10-11):

- Contract command: `npm run test:competitor-management:contract` — pass, 8 assertions across the source/schema contract file.
- Playwright command: `npm run test:competitor-management:e2e` — 15 BLOCKED, 0 pass/fail. No database or external calls were made.
- TypeScript: `npx tsc --noEmit` — pass.
- Combined `npm run test:all-features`: Dashboard, Demand Prediction, Product Management, and Competitor Management contracts passed. Existing Market Intelligence contract returned 2 pass / 4 fail for missing `market_intelligence`, `ai_pricing`, and `market_perception` entitlement checks. Shared feature E2E reported 40 BLOCKED, 0 pass/fail, including all 15 competitor scenarios.
- Shared diagnostics summary: `tests/reports/e2e/diagnostics.json` — PASS 0, FAIL 0, SKIP 0, BLOCKED 40, ERROR 0. The HTML report and Playwright JSON report are adjacent under `tests/reports/e2e/`.
