# Business Recommendations QA package

This package audits Feature 13 against the current CEOPRO source. It adds tests and diagnostics only; it does not change recommendation, billing, or customer-facing production behavior.

## Run it

From the `backend/` directory:

```sh
npm run test:business-recommendations
```

Focused commands are `test:business-recommendations:node-contract`, `:deterministic`, `:python`, `:ai-db`, `:frontend`, and `:live-ai-api`. The PowerShell equivalent is `tests/runners/run-business-recommendations-tests.ps1`.

The database suite skips unless `AI_TEST_DATABASE_URL` names a dedicated test/QA database and `AI_TEST_DATABASE_IDENTITY_VERIFIED=1`. On connection, the helper verifies the exact database name and rejects superuser or `BYPASSRLS` roles. The optional live AI endpoint probe is read-only and requires the explicit opt-in variables documented in `tests/e2e/business-recommendations/ai-api-live.spec.ts`. No production database or live endpoint was contacted for this run.

Reports and Playwright artifacts go to `tests/reports/business-recommendations/`; this keeps prior feature reports intact. The shared Playwright setup and dashboard diagnostics reporter are reused.

## Current implementation traced

The AI service serves a JWT-protected `GET /dashboard/recommendations?limit=3`, with a bounded limit and tenant identity from verified claims. It returns product ID, category, priority, and message. The Node backend has no customer recommendation proxy/route or commercial entitlement check for this path. The existing dashboard recommendation card is static sample copy and is not mounted by the dashboard page. As a result, browser cases that require a real customer flow are explicitly blocked; the AI JWT alone is not a subscription grant.

The production plan manifest excludes `business_recommendations` from Starter, Growth, and Enterprise. The catalog represents the feature as a lifetime boolean, and shared entitlement code supports custom feature grants, but this feature has no route consuming that check. The product owner still needs to define the final commercial exposure and subscription-change behavior before a customer endpoint is added.

## Signal sources and calculation contract

The SQL is in `ai/src/ai/insights/pipeline.py`; deterministic rules live in `cross_signal.py` and `causal_chain.py`.

| Signal | Current behavior observed in source | QA caveat |
|---|---|---|
| Price gap | Own product price versus the mean of latest competitor observations per mapping; `((own - competitor mean) / competitor mean) * 100`. | No same-currency filter/FX normalization, active/tracked mapping filter, availability filter, or freshness bound was found. |
| Sales trend | Sum invoice item quantities in recent and prior windows (30 days each); percent change is `(recent - prior) / prior * 100`; zero prior yields missing (`None`). | Reads `invoices` and `invoice_items`, not imported `transactions`; payment status and an upper bound against future invoice dates are not filtered. Returns/refunds are not netted. |
| Sentiment | Product review sentiment probabilities are combined; business-level sentiment can be used as fallback if product sentiment is absent. | No recency window; fallback should be disclosed in a future evidence-bearing UI. No competitor sentiment is used as product sentiment. |
| Forecast | Latest-created forecast per product compared to a recent-sales pace projected across the forecast horizon. | Expired targets are not rejected; model interval bounds are not used. |
| Price event | Competitor price-drop event followed by a decline in tenant sales pace over before/after windows. | Text is hedged as temporal association; the event is not proof of causation. |

SQL predicates are tenant-scoped and use the application tenant context. Confidence values are heuristic ranking signals, not calibrated outcome probabilities. Recommendations are generated on demand; this endpoint does not persist an outcome lifecycle or expose evidence records/stable recommendation IDs.

Invoice/transaction records must not be blindly added: the ingestion path can write `transactions`, while this AI trend query reads invoices. Tests preserve transaction-only, invoice-only, and same-sale cases for the eventual authoritative sales contract. Partial returns, duplicate imports, FX behavior, and product-variant policy remain unresolved by the current implementation.

## Results from this audit run

See `RESULTS.md` and `source-audit.json` for observed outcomes. The deterministic suite deliberately fails on six source regressions so they remain visible instead of being silently marked as passing. Database integration, pytest API tests, and customer-facing E2E cases were not represented as passes when their prerequisites were unavailable.

## Placement

Extract the ZIP into the directory that contains the sibling `backend/`, `ai/`, and `frontend/` project folders. The archive preserves those repo-relative paths. See the root `PLACEMENT.md` for the complete file map.
