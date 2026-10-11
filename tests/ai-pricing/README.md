# AI Pricing testing (Feature 15)

This is a test-only package. It preserves application defects as failing regression checks and does not change pricing, plan, entitlement, or customer data logic.

## Architecture and observed behavior

| Path | Current implementation | QA boundary |
|---|---|---|
| Customer path | `frontend/src/features/market-intelligence` → authenticated Node `POST /features/pricing/recommend` → Gradio `analytics/recommend` | The route currently has `requireEntitlement("ai_pricing")` commented out. The service calls Gradio before incrementing usage. |
| AI-team path | FastAPI `/pricing/recommend` → tenant context → Python pricing pipeline → PostgreSQL evidence/outcome | Independent implementation; it has no Node subscription usage integration and is not evidence that the customer Gradio route passed. |

Main source paths from the workspace roots are `backend/src/modules/pricing/{route,controller,service,repo,client}`, `backend/src/modules/features/catalog.ts`, `backend/src/config/production-plans.ts`, `ai/src/ai/pricing`, and `frontend/src/features/market-intelligence`.

`ai_pricing` is a summed numeric recommendation limit that resets by billing period. Starter, Growth, and Enterprise omit it in the current production plan catalog. Custom plan definition support exists, but the active recommendation route does not enforce the allocation. No charge/refund policy for UNKNOWN, provider errors, retries, repeated Refresh, or cached results is encoded in the active path; tests do not invent one.

## Pricing inputs and business rules

- Node queries eligible market rows from the previous 30 days: active tenant mapping, tracked competitor, available, exact, ALLOWED source. It currently returns multiple observations per mapping rather than selecting only the latest. Its market average/median are computed from all returned observations.
- The AI-team Python path selects same-currency rows for recommendation. Other currencies are reference-only and are not blended. It also currently returns every eligible observation in the window.
- Both paths lack an enforced FX age/positive-rate guard. The Python conversion multiplies by the matched pair rate; identity conversion keeps the original amount. Neither path supplies a robust bidirectional/latest-per-competitor guarantee.
- Python's decision threshold is strict: market average more than 5% below own price → lower; more than 5% above → raise; equality and the interval between → hold. No eligible local competitor data → UNKNOWN.
- Python caps price movement at 15%, then applies a minimum selling price of cost × 1.10. In a conflict, the cost floor can exceed the 15% cap. This test records current behavior without claiming the precedence is approved policy.
- Confidence is a bounded rule heuristic capped at 0.75, not a probability of success.
- Both implementations are expected to preserve the catalog selling price during recommendation generation. Python evidence carries competitor observation IDs; Node evidence currently stores `product_id` only.

## Test layers and current limits

- Node source contract regression checks cover plan availability, auth/tenant scoping, entitlement and usage order, atomic quota/idempotency gaps, market selection, FX freshness, provenance, no catalog price mutation, frontend availability/history, and the separate FastAPI route.
- Gradio contract tests exercise the real Node client serializer and response schema with a controlled test client. They are not live hosted AI tests.
- Deterministic Python tests call the AI-team pricing/guardrail functions. A subset intentionally fails on latest observation, zero-price exclusion, stale FX, and invalid FX requirements.
- PostgreSQL integration tests are opt-in and require `AI_TEST_DATABASE_URL` naming a dedicated test/QA database plus `AI_TEST_DATABASE_IDENTITY_VERIFIED=1`. They verify the connected database name and require a non-superuser, non-BYPASSRLS role before creating any synthetic rows. Cleanup is limited to fixture-owned tenant and competitor records.
- Full customer E2E is opt-in with `AI_PRICING_RUN_LIVE_E2E=1` and the existing `MARKET_INTELLIGENCE_TEST_*` variables plus `AI_PRICING_TEST_PRODUCT_ID`. It exercises browser → Node → configured hosted Gradio with no API mock. It writes recommendation evidence/outcome for that dedicated test tenant. It verifies persistence and unchanged product price.
- AI-team DB pipeline integration is not the same as an HTTP FastAPI test. A true FastAPI test-client integration still requires a dedicated service/JWT/db harness and remains blocked until that harness is configured.
- Quota boundary/concurrency, custom-plan lifecycle, retries/idempotency behavior, cross-tenant recommendation/evidence access, and Arabic AI Pricing presentation need application-facing test APIs or stable dedicated fixtures. They are represented by regression contract checks or marked blocked; they are not reported as runtime passes.

## Run from Windows PowerShell

From `backend`:

```powershell
npm run test:ai-pricing
npm run test:ai-pricing:contract
npm run test:ai-pricing:gradio-contract
npm run test:ai-pricing:deterministic
npm run test:ai-pricing:database
npm run test:ai-pricing:fastapi
npm run test:ai-pricing:e2e
npm run test:ai-pricing:frontend
npm run test:ai-pricing:live-gradio
npm run test:ai-pricing:headed
npm run test:ai-pricing:report
```

Runner modes offer focused selection and write a JSON run summary:

```powershell
.\tests\runners\run-ai-pricing-tests.ps1 -Mode All
.\tests\runners\run-ai-pricing-tests.ps1 -Mode Entitlements
.\tests\runners\run-ai-pricing-tests.ps1 -Mode Usage
.\tests\runners\run-ai-pricing-tests.ps1 -Mode Concurrency
.\tests\runners\run-ai-pricing-tests.ps1 -Mode Competitor
.\tests\runners\run-ai-pricing-tests.ps1 -Mode FX
.\tests\runners\run-ai-pricing-tests.ps1 -Mode Safeguards
.\tests\runners\run-ai-pricing-tests.ps1 -Mode Evidence
.\tests\runners\run-ai-pricing-tests.ps1 -Mode FastApi
.\tests\runners\run-ai-pricing-tests.ps1 -Mode TenantIsolation
.\tests\runners\run-ai-pricing-tests.ps1 -Mode E2E
.\tests\runners\run-ai-pricing-tests.ps1 -Mode LiveGradio
.\tests\runners\run-ai-pricing-tests.ps1 -Mode Single -Grep "market average"
.\tests\runners\run-ai-pricing-tests.ps1 -Mode Headed
.\tests\runners\run-ai-pricing-tests.ps1 -Mode Report
.\tests\runners\run-ai-pricing-tests.ps1 -Mode Previous
```

For live testing, use only a disposable tenant/product and verified QA database. Configure the existing `MARKET_INTELLIGENCE_TEST_ACCESS_TOKEN`, `MARKET_INTELLIGENCE_TEST_TENANT_ID`, `MARKET_INTELLIGENCE_TEST_USER_ID`, `MARKET_INTELLIGENCE_TEST_DATABASE_URL`, frontend/API URLs, and `AI_PRICING_TEST_PRODUCT_ID`; explicitly set `AI_PRICING_TEST_TENANT_APPROVED=1` and `AI_PRICING_RUN_LIVE_E2E=1` only when hosted calls, provider cost, and test-tenant writes are approved. The standalone Python DB suite uses its separate `AI_TEST_DATABASE_URL` and identity flag. Never point these at production.

## Results and diagnostics

Playwright HTML, JSON, traces, screenshots, and structured classifications write under `tests/reports/ai-pricing/`. `PASS`, `FAIL`, `SKIP`, `BLOCKED`, and `ERROR` remain distinct. Node source regressions and deterministic algorithm failures are expected evidence of current application/data-policy gaps; they must not be converted to passes by modifying production behavior in this testing package.
