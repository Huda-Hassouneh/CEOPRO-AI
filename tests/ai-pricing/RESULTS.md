# Feature 15 execution results

Run on 2026-10-11 from `backend/`. These results distinguish reproducible code regressions from tests blocked by missing safe infrastructure.

## Feature 15 results

| Layer | Result | Evidence |
|---|---|---|
| Node AI Pricing source contracts | **FAIL — 12 passed, 10 failed of 22** | `../reports/ai-pricing/package-run.log` |
| Node → Gradio client contract | **PASS** | five declared contract cases in `pricing-gradio-contract.test.ts`; command exited 0 |
| Python deterministic pricing | **FAIL — 9 passed, 5 failing assertions across 13 methods** | `../reports/ai-pricing/python-deterministic-results.json` |
| Python pricing PostgreSQL/RLS integration | **BLOCKED** | `AI_TEST_DATABASE_URL` and its verified-identity flag are not configured; no database write was attempted |
| Authenticated Arabic UI Playwright | **BLOCKED — 1 skipped** | no disposable tenant credentials/product configured |
| Full browser → Node → hosted Gradio | **BLOCKED — 1 skipped** | opt-in, explicitly approved disposable tenant, provider-cost approval, token, and QA DB not configured |
| Playwright HTML / JSON diagnostics | **Generated** | `../reports/ai-pricing/html/index.html`, `../reports/ai-pricing/playwright-report.json`, `../reports/ai-pricing/diagnostics.json` |

### Node source regressions

The ten failing contracts identify current gaps:

- `AI_PRICING_ENTITLEMENT_BYPASS`: the recommendation route does not enforce `ai_pricing` before controller invocation.
- `AI_PRICING_QUOTA_EXCEEDED` / `AI_PRICING_USAGE_NOT_CHARGED`: the service calls Gradio before `incrementUsage`, and ignores a missing-allocation result.
- `AI_PRICING_PERSISTENCE_FAILURE`: usage settlement is separate from evidence/outcome persistence; no atomic reservation contract is present.
- `AI_PRICING_DUPLICATE_CHARGE`: no request idempotency identity or persistence constraint protects retries/Refresh.
- `AI_PRICING_COMPETITOR_SELECTION_ERROR`: Node does not select only the latest observation per tracked mapping.
- `AI_PRICING_FX_RATE_STALE`: Node does not validate FX freshness and positive values before passing rates to Gradio.
- `AI_PRICING_EVIDENCE_INCOMPLETE`: Node evidence currently stores `product_id`, not the competitor observation IDs and timestamps used.
- `AI_PRICING_FALSE_SUCCESS_UI`: Generate/Refresh is shown without entitlement/remaining-credit state.
- `AI_PRICING_FRONTEND_MISMATCH`: generated recommendations are held in component state; no history retrieval is wired.

The passing Node checks confirm the `ai_pricing` catalog shape, exclusion from Starter/Growth/Enterprise, generic custom-plan numeric-limit persistence, authenticated tenant/product request scoping, evidence/outcome transaction, separate Node and FastAPI paths, no product-price writes, translated English/Arabic strings, and bounded response schema.

### Python deterministic failures

- FX conversion accepts a 2024 rate in the stale-rate regression.
- FX conversion accepts zero and negative rates (two failing subcases).
- Python market input query returns multiple eligible rows for a competitor instead of only its latest observation.
- Python market input query does not exclude zero prices.

The passing deterministic cases verify market min/max/average/median, strict 5% decision boundaries, Raise/Lower/Hold/Unknown behavior, cross-currency reference prices not being blended, 15% movement caps, 10% cost markup, current cap/floor conflict behavior, confidence capped as a heuristic at 0.75, valid FX conversion, and FastAPI evidence source IDs.

The guardrail conflict test passes against current code: the cost floor is applied after the movement cap and can exceed the cap. The business precedence remains unresolved; the test records current behavior without choosing a new policy.

## Previous feature regression run

`npm run test:all-features` ran the existing combined feature runner plus Feature 15. It exited 1 with **9 failed suite groups and 2 blocked groups**. The full console log is `../reports/ai-pricing/all-feature-regression.log`.

Failed groups:

- Market Intelligence contract (4 of 6 checks failed; includes the existing pricing entitlement assertion).
- Connected Data Sources contract and quota regressions.
- Document Extraction contract/regression checks.
- Document Storage contract/regression checks.
- RAG Assistant source regressions.
- Business Recommendations deterministic AI rule tests.
- Smart Alerts deterministic calculations/source regressions.
- Feature 15 Node authorization/usage/evidence contracts.
- Feature 15 Python pricing regressions.

Blocked groups:

- Business Recommendations Python AI/API tests (Python test dependency unavailable).
- Feature 15 PostgreSQL integration (no explicitly verified QA database configured).

Dashboard, Demand Prediction, Product Management, Competitor Management, Data Integration, RAG provider contracts, Business Recommendations Node/catalog checks, Smart Alerts source contracts, notification contracts, and the gated Playwright group did not add a suite-level failure in this run. Individual E2E scenarios report their own BLOCKED states in their test diagnostics; they are not counted as verified passes.

## Other validation

- `npx playwright test --config playwright.ai-pricing.config.ts tests/e2e/ai-pricing --list`: PASS, discovered 2 tests.
- `node --check` for new/changed JavaScript runners and source contract: PASS.
- Python `py_compile` for the new deterministic runner and touched integration test: PASS.
- `package.json` JSON parse: PASS.
- TypeScript Gradio contract test file: PASS.

The accidental initial browser launch identified Chromium is not installed in this environment. The final browser run skipped before launching because credentials/approved test fixtures were absent. No screenshots or traces are claimed for blocked browser scenarios.
