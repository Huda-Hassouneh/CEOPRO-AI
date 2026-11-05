# Engineering report — 2026-11-05 session

Branch `claude/jolly-lamport-ff1a31`, started from `main` at `aaa725e`. All changes are pushed to
that branch; nothing was merged, deployed or run against production. Status words: **PASS**
(verified with evidence), **IMPLEMENTED** (code + unit tests, not verified end to end here),
**BLOCKED** (needs access this environment does not have), **OPEN** (known, not fixed).

## A. Executive summary

- **Assistant question understanding** now has an honest, repeatable benchmark (dev + sealed
  holdout). A root-cause fix for Arabic product names raised holdout accuracy from **82.2% to 93.2%**
  (Arabic 61.3% → 87.1%; product resolution 67.9% → 100%).
- **Forecast ranges were overconfident**: labelled 80%, they held the actual 30-day total only
  **55.6%** of the time in backtests. Now calibrated: **79.0%** on an independent test split. A
  production-path backtest harness with segment tables, WAPE, MASE, bias and coverage was added.
- **Real-browser new-customer journey** (sign-up → email code → onboarding → every main screen) found
  and fixed 4 user-facing defects, including a select bug that made the first option of several
  onboarding lists impossible to choose and blocked Continue.
- **Initial JavaScript halved**: 717 kB → 360 kB (202 → 108 kB gzip) by lazy-loading the Platform Owner console.
- **Financial safety**: an imported line total above quantity × price is now held for review instead
  of being silently replaced.
- **Security review**: no new vulnerability found; live cross-tenant probe, headers, CORS, throttling,
  SSRF and dependency audits all PASS. Render, live LLM and image providers are **BLOCKED** here.

## B. Code changes

| Subsystem | Files |
|---|---|
| Frontend performance | `frontend/src/features/platform-admin/routes.jsx` |
| Assistant understanding | `backend/src/ai/rag/understanding.py`; new `backend/src/ai/rag/eval/understanding_benchmark/` (README, catalog, dev, holdout, holdout.sha256); new `backend/scripts/evaluate_understanding.py`; new `backend/src/ai/tests/test_understanding_benchmark.py`; results `backend/reports/understanding/*.json` |
| Forecasting | `backend/src/ai/forecasting/pipeline.py` (`forecast_interval`, `_horizon_total_errors`); `backend/src/ai/forecasting/README.md`; new `backend/scripts/evaluate_forecast_pipeline.py`; new `backend/src/ai/tests/test_forecast_interval_calibration.py`; results `backend/reports/forecasting/pipeline_*.json` |
| Onboarding / shared UI | `frontend/src/shared/components/ui/Select.jsx`; `frontend/src/features/onboarding/pages/OnboardingRegionalPreferencesPage.jsx`; `backend/src/ai/onboarding_profile.py`; new `backend/src/ai/tests/test_onboarding_suggested_country.py`; locales |
| Marketing / billing UI | `frontend/src/features/marketing/pages/MarketingStudioPage.jsx`; `frontend/src/features/marketing/styles/Marketing.css`; `frontend/src/features/billing/hooks/useBillingResource.js` |
| Imports | `backend/src/ai/extraction/typed_imports.py`; new `backend/src/ai/tests/test_import_paid_total_conflict.py`; locales |
| Docs | this report; `docs/PRESENTATION_DEMO_GUIDE.md`; `docs/evidence/2026-11-05/*.jpg` |

## C. Bugs fixed

| # | Problem | Root cause | Fix | Verification |
|---|---|---|---|---|
| 1 | Every customer downloaded the whole Platform Owner console | Admin routes statically imported | Lazy screens outside idle prefetch; guard stays eager | Build: index 717→360 kB; 266/266 frontend tests |
| 2 | Arabic questions naming "التمر", "العسل", "الزيت" found no product | Partial-name match required ≥4 letters for every script; Arabic nouns are 3 letters once ال is removed; كغ/غم counted as name words | Arabic ≥3, Latin ≥4; Arabic units treated as generic | Benchmark (below); 272 existing understanding tests pass |
| 3 | "Why do customers prefer imported rice?" triggered customs research | "imported" adjective matched the `import` trade keyword | Attribute-only "imported" no longer implies trade | Benchmark + unit test |
| 4 | "Do customers like…", "losing money", "how can I increase…" missed | Missing cues | Added opinion, loss and advice cues | Dev benchmark |
| 5 | Forecast "80%" range held 55.6% of outcomes | Assumed independent days (σ·√h) | Range ≥ 80th percentile of the baseline's own past horizon-total misses (≤12 weekly origins, ≥4 required) | Test split coverage 79.0%; 3 unit tests; 246 forecasting tests pass |
| 6 | Onboarding showed "Belgium"/"Under $100K" as chosen while nothing was; those options were unselectable; Continue disabled | Controlled `<select>` with empty value and no empty option | Shared `Select` renders a hidden placeholder for empty values | Browser walk completes onboarding |
| 7 | Country chosen at sign-up asked again | Not carried into onboarding | `suggestedCountry` from the company record (never saved until confirmed) | Browser: step 1 shows Jordan; unit tests |
| 8 | Marketing opened on an empty product list for new companies | Default tab "My product" | Starts on "Describe it" when the catalog is empty, until the owner picks a tab | Browser screenshots (EN/AR) |
| 9 | "Creating the image…" shown when no image was being made | Timer switched text after 6 s unconditionally | Only when this request makes an image inline | Code review; browser |
| 10 | Billing page logged 16 React Query errors per visit | Disabled query without `queryFn` | `skipToken` | Browser sweep: 0 errors |
| 11 | Imported line total above qty × price silently replaced | Fallback to qty × price in promotion | Typed row gets `paid_total_exceeds_quantity_times_price_requires_review` | 3 unit tests; 362 import tests pass |
| 12 | Phones: four full-width goal cards before the Create button | Layout | 2×2 compact grid ≤560 px | Arabic mobile page ~1550 px shorter |

## D. AI benchmark results — question understanding

Deterministic layer only (intents, calendar periods, catalog products); not LLM wording.
Dataset: `backend/src/ai/rag/eval/understanding_benchmark/` — 76 dev + 73 holdout questions,
English / Arabic (MSA, Levantine incl. Jordanian, Gulf, Egyptian) / mixed, with follow-ups.
Both splits were written before the system was run on either; the holdout was scored once before
and once after the fixes, aggregate only (per-item failures never inspected). Because it has now
been reported after tuning, future work needs a new holdout.

| Split | Metric | Before | After |
|---|---|---|---|
| Holdout (73) | Fully correct | 82.2% (95% CI 71.9–89.3) | **93.2%** (85.0–97.0) |
| | Intent | 94.5% | 94.5% |
| | Period (22 labelled) | 95.5% | 95.5% |
| | Product (28 labelled) | 67.9% | **100%** |
| | Arabic / English / mixed | 61.3% / 97.2% / 100% | **87.1%** / 97.2% / 100% |
| | Levantine / MSA / Gulf / Egyptian | 60% / 71% / 67% / 50% | 87% / 100% / 67% / 50% (n=15/14/3/2) |
| Dev (76) | Fully correct | 86.8% | 100% (tuned on) |
| | Latency | median ~1.6 ms, p95 ~4 ms per question (CPU) | |

Not measured (BLOCKED — no working LLM key): retrieval Recall@K/Precision@K on real tenant
documents, grounded-answer rate, hallucination rate, end-to-end answer correctness. The 98% target
is **not** reached on the holdout (93.2%); Gulf/Egyptian samples are too small to conclude anything.

Product matching (existing labelled set, scored unchanged): exact-match precision **100%** (dev 142,
holdout 123 pairs), like-for-like precision 98.8% / 100%, settled accuracy 93.4% / 87.9%; 16–21 pairs
held for human review rather than auto-matched.

## E. Forecasting results

`backend/scripts/evaluate_forecast_pipeline.py` backtests the production choice on 30-day totals:
7 synthetic segments × 12 test seeds × 3 non-overlapping origins = 252 windows (no real history
exists in the repository; dev seeds were used for diagnosis only). Full tables in
`backend/src/ai/forecasting/README.md`.

| 30-day totals, test split | Pipeline | Naive | Seasonal naive | MA-28 | SES | Damped Holt |
|---|---|---|---|---|---|---|
| WAPE % | **10.5** | 38.7 | 14.2 | 13.9 | 15.6 | 16.9 |
| Bias % | −3.9 | +10.0 | −4.4 | −0.3 | −2.1 | −2.4 |

80% range coverage: **55.6% → 79.0%** (30-day); 77.0% at 7 days. Median width rose 0.14 → 0.23 of
the actual total. **OPEN**: declining products are over-forecast ~14% (seasonal naive and damped
Holt beat the pipeline there); 7-day windows starting on an unannounced promotion are not
foreseeable without a promotions calendar.

## F. Image model comparison

**BLOCKED — no images were generated, so no speed, success-rate or quality figures are reported.**
Integrated providers (from `backend/src/ai/marketing/image_generation.py`): Cloudflare Workers AI
(FLUX.1 schnell, fallback models), Hugging Face Inference, Together AI, Gemini image, Pollinations
(keyed only — keyless output is watermarked and refused), AI Horde, and the self-hosted SDXL 1.0
image server (`backend/image_server`, earlier measured ~24–27 images/hour on 4 CPU cores, 10.2 GB peak).
In this environment the Hugging Face token returns 401, the other provider hosts are refused by the
sandbox network policy, and the self-hosted server needs PyTorch and model weights that could not be
downloaded (CPU PyTorch index blocked). Using an owner's uploaded product photo as a generation
reference must not be sent to an external provider without explicit approval and a privacy
assessment; the UI already states that photos are never sent.

## G. Frontend evidence

Real browser (Playwright/Chromium) against the local API and a disposable database:
- Journey: sign-up → email code (from the local log; no SMTP) → 6 onboarding steps → dashboard: PASS.
- Sweep of 11 screens (dashboard, products, demand, pricing, reports, competitors, marketing,
  assistant, data & documents, settings, billing), English desktop 1366×900 and Arabic iPhone 13:
  **0 console errors, 0 HTTP errors, 0 px horizontal overflow, `ar/rtl` and `en/ltr` correct**.
- Screenshots: `docs/evidence/2026-11-05/` (EN desktop dashboard, marketing, demand; AR mobile
  dashboard, marketing, assistant). Tablet was not separately captured.

## H. Test results

| Suite | Result |
|---|---|
| Frontend lint | PASS (clean) |
| Frontend unit tests (`node --test`) | **266 passed, 0 failed** |
| Frontend production build | PASS; index 360 kB (108 kB gzip) |
| `npm audit --omit=dev` (high) | 0 vulnerabilities |
| Backend `pytest src/` on a disposable PostgreSQL 16 + pgvector and Redis | **4738 passed, 71 skipped, 15 failed** |
| — failures explained | 13 need PyTorch / `huggingface_hub` (blocked download: image server, ONNX/static embedding backends); 1 asserts PostgreSQL ≥17 (sandbox has 16); 1 billing contract test fails only on a re-used database (leftover singleton row) and **passes on a freshly migrated database** |
| — not collected | 3 sentiment model test files (need PyTorch) |
| `pip-audit` of installed backend packages | 0 known vulnerabilities (PyTorch stack not installed, not audited) |
| Real Tesseract OCR tests (English, Arabic, scanned PDF) | PASS |
| `tests/` (billing/entitlements runners) | NOT RUN — designed for the isolated runner (`dev.ps1`), which needs Docker |
| Live LLM, image, Stripe, SMTP, merchant tests | BLOCKED (credentials/network) |

All 160 migrations apply cleanly to a fresh database.

## I. Security findings

| Check | Result |
|---|---|
| Cross-tenant: company B on company A's product (GET/PATCH/inventory/DELETE) | PASS — 404 each; A's record intact; spoofed `X-Tenant-ID` ignored |
| Unauthenticated and `alg=none` tokens | PASS — 401 |
| Login brute force | PASS — 429 after 10 failures |
| Security headers | PASS — HSTS, CSP `default-src 'none'`, `X-Frame-Options: DENY`, nosniff, no-referrer, Permissions-Policy |
| CORS from a foreign origin | PASS — no `Access-Control-Allow-Origin` returned |
| SSRF (product links, connectors) | PASS by review — public-address check per redirect hop, connection pinned to the checked IP, size cap |
| Upload limits | PASS by review — bounded reads, 413 above 10 MB |
| Secrets in tree/history | No real hosted-database credential found (only example/CI throwaway values); earlier exposures remain as documented in `docs/SECURITY_CREDENTIAL_ROTATION.md` — **rotation still OPEN (owner action)** |
| **Environment risk (new)** | This cloud session's environment injects `DATABASE_URL`/`SCRAPER_DATABASE_URL` for a Render-hosted PostgreSQL with an admin-level role. Running the test suite or migrations without overriding them would target that database. All work here used local disposable databases. Recommend removing these variables from the agent environment or pointing them at a disposable database. |

## J. Render infrastructure

**BLOCKED.** No Render API credential exists in this environment and `api.render.com` and
`*.onrender.com` are refused by the sandbox network policy; the hosted database host is not
resolvable from here either. Service status, deploy logs, environment completeness and staging
health could not be inspected. The last recorded state (`docs/FINAL_SYSTEM_AUDIT.md`, 2026-10-21) was:
frontend served, API not answering `/health` — root cause unconfirmed. To unblock: add a Render API
key as a session credential and allow `api.render.com`, or run the checks from a machine with access.

## K. Presentation readiness

Can be shown confidently (with a seeded synthetic tenant): sign-up and bilingual onboarding,
dashboard and empty states, products/inventory, data import with review, demand forecasts with
methods and calibrated ranges, product-match review, security architecture and the isolation probe.
Requires configuration on the demo server first: assistant answers and marketing copy (valid LLM key
+ approved price), images (a working provider), payments, email. See `docs/PRESENTATION_DEMO_GUIDE.md`.

## L. Remaining work (by severity)

1. **High** — Rotate credentials exposed in public history (owner action; see rotation doc).
2. **High** — Restore staging (needs Render access) and verify `/health/ready` and the critical journeys there.
3. **High** — Provide a valid LLM key + approved price on the demo/staging server; then measure retrieval recall/precision, grounded-answer and hallucination rates on a seeded tenant.
4. **Medium** — Forecasting: declining products over-forecast ~14%; evaluate a trend-aware blend on dev seeds, confirm on a new test split.
5. **Medium** — Image generation: configure one free-tier provider and measure latency/success/quality; privacy assessment before any reference-photo feature.
6. **Medium** — Remove the hosted `DATABASE_URL` from the agent environment (see I).
7. **Low** — New understanding holdout for future tuning; more Gulf/Egyptian items.
8. **Low** — Make `test_standard_plan_creation_contract.py` re-runnable on a reused database.
9. ~~**Low** — Verify-email copy said "We sent a code" while also showing "could not deliver"~~ — fixed in this session.

## M. Git status

Branch `claude/jolly-lamport-ff1a31`, pushed to `origin`. Session commits (oldest first):
`7302520` admin lazy-load · `fe95d94` understanding benchmark + Arabic matching · `bdbc214` forecast
range calibration · `64e4611` onboarding selects + country · `9971ace` marketing/billing UI · `9c84de3`
import paid-total review · plus this documentation commit. No pull request was opened. No uncommitted
changes beyond local runtime files outside the repository.
