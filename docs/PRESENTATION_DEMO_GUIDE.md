# KEEL — demonstration guide for evaluators

A short, factual briefing for presenting KEEL to a technical and business committee.
Everything under "Verified" has evidence in this repository; everything else is labelled
as what it is. Measured figures come from [the 2026-11-05 engineering report](ENGINEERING_REPORT_2026-11-05.md).

## 1. What KEEL is

A multi-tenant business-intelligence and commerce-operations web application for small and
growing businesses, in English and Arabic (full right-to-left layout). Owners bring products,
sales exports, stock, invoices and documents; KEEL turns them into dashboards, demand forecasts,
pricing evidence, cited answers to business questions and marketing drafts.

## 2. Problems it addresses

- Sales, stock and competitor prices live in spreadsheets, POS exports and paper invoices.
- Owners re-order by instinct: stock-outs and over-stock both cost money.
- Asking "how did olive oil do last month compared with September?" needs an analyst.
- Marketing content takes time and often states things the business cannot support.

## 3. Target users

Owners and managers of small retail, food, and e-commerce businesses — initially Jordan and the
wider Arabic-speaking region (Levantine, Gulf and Egyptian wording is handled), with English
support everywhere.

## 4. What is different

- **Bilingual by construction**: Arabic and English UI, Arabic dialect and mixed-language questions,
  Arabic-Indic numerals in documents.
- **Honest by design**: empty or insufficient data is shown as such; unconfigured AI says so instead
  of inventing output; uncertain product matches are held for review rather than auto-accepted.
- **Evidence-first**: forecasts carry backtested ranges and the method used; assistant answers cite
  their sources; competitor prices keep provenance.

## 5. How the AI works (in one paragraph each)

**Question understanding and the assistant.** Every question is first read by a deterministic
layer (`backend/src/ai/rag/understanding.py`, `periods.py`) that decides what evidence is needed
(sales, stock, documents, outside research…), the exact calendar dates meant ("last month",
"الربع الثالث", "شهر 9") and which catalog products are named. Numbers then come from exact SQL
over the company's own records; documents come from tenant-scoped hybrid retrieval (BM25 plus
optional embeddings); a language model only writes the answer around that evidence, with citations.

**Forecasting.** For each product, KEEL backtests several simple methods (naive, seasonal naive,
moving averages, a recent blend) on past 30-day totals and uses XGBoost only when it beats all of
them both one day ahead and on the horizon total. Isolated outliers (a mistyped 50,000) are capped
and disclosed; intermittent sellers use period-total baselines. Each forecast stores an 80% range
calibrated against how much past horizon totals were actually missed.

**Marketing.** One screen: describe a product (or pick one, or paste a link), choose a goal, press
Create. The writer receives only facts from the product record or the owner's text; unsupported
claims (origin, certification, health) are checked against those sources. Images come from a
configured provider (cloud free tiers or a self-hosted Stable Diffusion XL server).

**Document extraction.** CSV/Excel/PDF/image uploads go through template detection, OCR
(Tesseract, Arabic + English), typed validation and a human review step before anything reaches
revenue. Financial lines that do not reconcile are held for review.

## 6. Security and tenant isolation

- PostgreSQL **FORCE row-level security** on tenant tables, accessed through a restricted
  `ceopro_app` role; separate least-privilege roles for billing setup, Stripe webhooks and credit
  accounting.
- Every request derives the tenant from a signed session; a header naming another tenant is ignored.
- Login throttling, per-tenant and per-address rate limits, strict security headers, exact-origin CORS.
- Outbound fetches (product links, connectors) are SSRF-guarded: public addresses only, each redirect
  re-checked, connection pinned to the checked IP.
- Stripe webhooks are signature-verified and idempotent; payment-gated access.

## 7. Verified (with evidence)

| Area | Evidence |
|---|---|
| New-customer journey: sign-up → email code → 6-step onboarding → dashboard | Real browser run, 2026-11-05 |
| 11 main screens, English desktop and Arabic mobile | 0 console/HTTP errors, 0 px horizontal overflow, correct `dir` |
| Cross-tenant isolation | Live API probe: other company's product → 404 on read/update/delete; automated isolation tests pass |
| Question understanding (deterministic layer) | Sealed holdout: 93.2% fully correct (73 items); Arabic 87.1%; product resolution 100% |
| Forecast range calibration | Synthetic test split: 80% range covers 79.0% of actual 30-day totals (was 55.6%) |
| Product matching | Labelled holdout: exact-match precision 100%; uncertain pairs held for review |
| Backend / frontend automated tests | See the engineering report (thousands of tests, live database) |

## 8. Implemented but not verified in this environment

- **Live AI writing** (assistant prose, marketing copy): the configured Groq key is rejected; the
  product shows an honest "not set up" message. A valid key plus an approved price is needed.
- **Image generation**: no working provider credential and provider hosts are not reachable from the
  build environment. Do **not** show generated images unless produced live on the demo server.
- **Stripe payments, email delivery, Shopify/WooCommerce sync, competitor web collection**: need
  their accounts configured on the demo server.
- **Staging on Render**: not inspectable from the build environment (see the report).

## 9. Experimental

- XGBoost demand model (selected in a minority of backtest windows; baselines usually win).
- Sentiment fine-tuning, self-hosted image server (CPU: roughly 24–27 images/hour measured earlier).

## 10. Infrastructure limits

Render free plan: services sleep when idle (first request can take tens of seconds), limited memory,
and background workers require a paid plan, so forecast/image/market workers are disabled on staging.
These are hosting limits, not application defects.

## 11. Suggested 10-minute demo flow

1. **Sign up** in Arabic or English; show the email code step and guided onboarding (country carried over).
2. **Dashboard empty state** → the four-step setup list explains what unlocks what.
3. **Import a sales file** (Data & Documents) → review screen → confirm. Point out a held-for-review line.
4. **Demand** for one product: forecast, method used, the 80% range and the outlier disclosure.
5. **Assistant**: ask "قديش بعنا زيت الزيتون الشهر الماضي؟" then "وبالشهر اللي قبله؟" — dates and product carried over, cited answer *(requires a working LLM key on the demo server)*.
6. **Marketing**: describe a product in one sentence → Create *(requires a configured writer/image provider)*.
7. **Security slide**: RLS, restricted roles, the live cross-tenant probe result.

Prepare the demo tenant with the documented synthetic seed (`tools/dev/seed_meeting_demo.py`,
see `docs/DEMO_SEED_PHASE1.md`), never real customer data.

## 12. Future opportunities

Promotions calendar input for forecasts; trend-aware forecasting for declining products; a
privacy-reviewed option to use the owner's own product photo as an image reference; more Arabic
dialect coverage measured on a fresh holdout; uptime monitoring and error tracking on staging.
