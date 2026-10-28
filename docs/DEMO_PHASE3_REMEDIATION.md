# Phase 3 — Customer acceptance remediation

Date: **2026-10-28, Asia/Amman**. Starting HEAD:
`697561a8aef37a4255ac0a774df9714beb67c2d6`, branch
`integration/keel-full-migration`, checkout `E:\KEEL START\CEOPRO-AI`.
The local commit adding this report contains the scoped implementation and
regressions. Pre-existing Phase 1/2 files and changes are excluded from it.

**Result: PASS for the five scoped tasks**, with the bounded verification and
remaining limitations below. This does not convert the entire Phase 2 feature
matrix into full acceptance. No seeding, financial-policy change, migration,
permission grant, database reset, push or deployment was performed.

## Defects, reproduction and resulting behavior

| Issue | Before / reproduction | Fix and expected-versus-actual result | Status |
|---|---|---|---|
| RAG historical scope | The Phase 2 real question requested all sales history but cited the 90-day summary: 4L oil JOD 18,315. Five initial AI regressions failed before implementation, including English/Arabic scope and follow-up handling. | Explicit all-history scope now selects tenant-scoped live invoices and line totals over every stored date, separated by currency. Fixed-window generated sales summaries and default-window analysis are excluded for this scope. A previous day-window or implicitly resolved top product is cleared when the period changes. Prompt requires disclosure if evidence cannot answer the requested scope. Real English and Arabic answers returned **4L oil JOD 33,132**, with `/reports` citations. | **PASS**, bounded |
| Marketing factual grounding | The saved real draft invented Amman-grown/bottled origin. The initial regression showed that such a draft returned successfully because the old generator only parsed JSON after a prompt-level instruction. | Separate supplied product facts from creative geography/theme. Review objective copy assertions against the actual source; require supporting quotations present in that source and claim spans present in the draft. Reject unsupported origin/certification/medical assertions even if a model review optimistically accepts them. One repair turn receives the actual rejected assertions; a second rejection or unavailable reviewer fails closed. Real English and Arabic campaigns completed after review, retaining hooks/captions without the known invented local-origin statements. | **PASS**, bounded |
| Market provenance | Starting-commit code and Phase 2 actual UI described manual entries as scan results/published website prices and exposed no per-price provenance. Baseline reproduction is retained separately from the new regression. | API distinguishes explicit new manual evidence, collection records linked by tenant/mapping/observation timestamp, and legacy manual-or-unrecorded sources. New manual entries record provenance in the existing tenant-isolated evidence store. Existing price rows are not rewritten. UI uses recorded-observation wording and English/Arabic source labels. A URL, ALLOWED collection status or exact-product flag is never treated as independent provider verification. | **PASS** |
| Twelve report failures | Reproduced exact combined selection: **12 failed, 51 passed**; the same report module alone passed 15 tests. Investigation established **email-verification rejection before handler/capability execution**, rather than a missing paid entitlement or weakened role permission. | Old hand-signed test tokens omitted `ev: true`. With the isolated runner's SMTP configured, automatic email verification correctly returned 403. Corrected the verified-user fixture; added explicit enforced-email success, unverified-session denial and staff denial tests. Original report scenarios pass in the combined selection. Production authorization code is unchanged. | **PASS** |
| Global billing drift | Compared retained Phase 1 restore with current rows using read-only transactions, reporting counts/field names/timestamps and pseudonymous tenant labels. | Stored evidence explains the earlier fingerprints as separate Stripe TEST Checkout/trial sequences and subscription updates. No billing defect requiring a change was proven; no billing rows were modified. Attribution to a human/process initiating the Checkouts remains unproven. See read-only findings below. | **PASS** for investigation; actor attribution unresolved |

### AI implementation and measured limits

Historical totals follow the same invoice/recorded-line definitions as Reports;
they are not estimates from retrieved prose. The new path returns the stored
date span and currency-specific totals, and ranks the top five recorded product
revenues. The regression includes a winning sale **400 days old** and a larger
foreign-tenant sale: the old sale is included and the foreign sale excluded.
Ordinary recent-window behavior remains covered by existing tests. Mixed-currency
amounts are not converted into one monetary total. This phase verifies explicit
all-history phrasing, not arbitrary date-range natural-language interpretation.

Marketing preserves creative opinions, cooking suggestions and proposed artwork;
objective product facts must come from the supplied source. The factual review
is model-assisted, with deterministic source-quote checks and sensitive-assertion
guards; it is not independent external certification or a proof that every
possible future marketing claim is true. Generated copy still deserves editorial
review before publication. Source facts supplied by a customer are not themselves
externally verified by this change.

Actual provider runs exposed two additional correctness details within this fix:
brand hashtags need spacing/case normalization when matching quoted draft spans,
and Arabic claim spans must retain their original language while source quotations
retain the source language. Both have regressions. A malformed Arabic JSON draft
also failed honestly; marketing now opts into the provider adapter's existing
JSON-object mode through a backward-compatible optional wrapper argument.

Draft and review calls both use existing provider metering and accumulate actual
plan-token usage. A successful first draft now requires two model calls; one
repair/review attempt can require four. Failed attempts may still incur actual
provider costs. No financial rates, credit allocations, pricing margins or failure
charging policies were changed. Provider rate limits and unavailable reviewers
remain genuine possible refusals; no canned successful provider response was used.

## Verification and evidence

Private evidence root: `.dev/evidence/meeting-phase3/`. Provider replies, private
fixtures, snapshots, logs, screenshots and backups remain untracked. The synthetic
payload was verified before external acceptance: all 1,800 source lines match the
explicitly synthetic generated manifest, with only the three designated demo
documents. Automatic approval review initially blocked the provider run as
potentially sensitive; the read-only synthetic-data proof allowed the retried run.
No unrelated customer information or credentials were submitted to Groq.

Real-provider tests ran on a **restored disposable clone**, with restricted
`ceopro_app` API credentials, isolated Redis/object storage, Groq only, Stripe
disabled and billing/discovery/digest/forecast background activity disabled.
The normal tenant's Credits, allowances and persisted chat/campaign outputs were
not consumed or replaced. The clone had the same source facts and actual verified
cost configuration from the backup; no new commercial configuration was invented.
Clone services were stopped after verification; retained databases/evidence remain
available for diagnosis.

| Verification | Result / evidence |
|---|---|
| Pre-fix AI reproduction | **5 failed as expected**: `.dev/evidence/phase3-ai-repro.log`. These establish the original defects, not a successful test run. |
| Pre-fix combined report reproduction | **12 failed, 51 passed** in `.dev/evidence/tests/bf6fa0866228/`; standalone report reproduction **15 passed** in `.dev/evidence/phase3-report-repro.log`. |
| Baseline provenance reproduction | `provenance-before.json`: original committed code plus an explicitly mocked manual row confirms missing provenance and misleading scan wording. Phase 2 real screenshots/responses provide customer evidence. |
| Focused isolated backend | **391 passed**, no skips, `.dev/evidence/tests/d7597453c754/backend.log`, `backend.xml`, `run.json`. Covers AI/advisor/provider, report, product/inventory, native market input, marketing lifecycle/storage, usage/Credits and RLS. |
| Final guard/scope/provider rerun | **190 passed**, `.dev/evidence/phase3-final-guards.log`; covers the last sensitive-origin guard, period-change reranking, bilingual spans, JSON mode and accumulated tokens. Counts overlap the broader suite and must not be added together. |
| Database security | Fresh disposable backend DB: **146 migrations, 120 FORCE RLS tables**, pgvector and restricted password login passed. No normal DB schema or role-policy change. |
| Frontend | **230 passed**, zero failures; ESLint and production build passed, `.dev/evidence/phase3-frontend.log`. Includes rendered provenance regression and locale checks. Existing build chunk/dynamic-import warnings remain. |
| Real Groq RAG | **PASS**, two actual English/Arabic UI submissions, HTTP 200, `answer_mode=ai`, correct JOD 33,132 and live-report references: `rag-en.private.json`, `rag-ar.private.json`. |
| Real Groq marketing | **PASS**, completed English and Arabic copy responses: `marketing-final-en.private.json`, `marketing-final-ar.private.json`. Earlier refusals are retained; they were not counted as passes. Actual draft/review traces show repair and supported-source checks; no mocked provider outputs. |
| Final real browser | **14 checks passed**, English desktop 1440px and Arabic mobile 390px: `browser-final.json`, `marketing-final-*.png`, `rag-final-*.png`, `provenance-final-*.png`. Exact persisted captions, history, citation panels, source labels and RTL checked. No new generation in this read-only pass. Mobile source columns use the existing scrollable table. |
| Clone settlement | Zero outstanding AI-credit reservations; consumed balance and cost reconcile exactly to actual ledger settlements under existing rounding. `preservation-final.json`. This is KEEL metering, not a Groq invoice certification. |
| Patch hygiene | `git diff --check` passed. No unrelated pre-existing changes are staged for this remediation commit. |

The initial `real-summary.json` records failures before the marketing fixes and
is retained as such. Final marketing responses plus `browser-final.json` are the
final acceptance evidence; do not relabel the initial run as successful.

## Original demo preservation

Before clone testing, exported a consistent private snapshot and restored it;
**139 table fingerprints matched**. A second pristine restore was retained for
the final comparison, because the first clone intentionally accumulated real
acceptance chat, campaigns and metering.

Final read-only Phase 1 reconciliation and Phase 3 preservation checks passed:

- **All 109 tenant-owned tables**, across the 13 tenants in the Phase 3 baseline,
  unchanged. This includes the demo's products, inventory, competitors, documents,
  forecasts, trial/subscription state, usage and Credits.
- **All global billing/Credits/usage/provider-cost fingerprints unchanged** since
  that baseline. No normal billing mutation endpoint or Stripe operation was called.
- All **1,800 original invoice-line facts** match the source manifest; 360 invoices,
  ten original active SKUs with their original prices/costs and all closing-stock
  quantities match. The previously soft-deleted disposable product is not counted
  as an active product and was not purged.
- Revenue **JOD 85,892.200**, gross profit **JOD 33,257.500**, 24 original manual
  competitor price observations and all three **40% overlap** classifications remain.
- Protected private configuration and `.env.example` hashes match the Phase 3
  baseline. No secret values are included in this report.

The entire normal database is **not byte-identical**: `image_workers` heartbeat
state and three additional `keel_platform_audit` actions named `me` changed during
the window. These operational observations are documented separately; neither
is a change to tenant business or financial records. Do not present the historical
Phase 1 global-preservation assertion as passing against an old snapshot: the
previously established unrelated billing drift still exists historically.

## Read-only billing findings

`billing-drift-readonly.json` compares the retained pre-seed Phase 1 restore to
current state. It found **25 added stored webhook events**, all with
`livemode=false`, including Test Clock creation, customer/Checkout/subscription
creation, setup-intent/payment-method events and invoice events. Two non-demo
tenant sequences correlate with new customers, Checkouts and trialing
subscriptions. Both newly recorded `billing_payments` rows have **zero amount**;
they are not evidence of paid post-trial access.

The two Checkout sequences were processed around **09:13–09:14** and
**10:08** Asia/Amman; separate subscription updates were processed around
**09:30**. The first sequence predates Phase 2 writes; the second occurred during
the earlier broad acceptance window, and the source of the Checkout request
cannot be attributed from these retained records alone. Test Clock association
is recorded where present, not assumed for every customer. No LIVE activity was
observed in the added stored events; this is a local-database observation, not
an audit of the entire Stripe account.

The demo's billing fingerprints remained unchanged. This investigation used only
read-only database transactions: no webhook replay, Checkout, payment, Test Clock
advance, subscription repair, financial backfill or global record edit.

## Updated 15-minute demonstration recommendations

The original demo remains usable. Normal URLs remain the configured frontend
`http://127.0.0.1:5173` and API `http://127.0.0.1:8000`; recheck `dev.ps1 status`
before the meeting. The clone's corrected chat/copy records were deliberately
not copied into the original tenant. Use saved verified screenshots for a
zero-generation fallback, or let the presenter submit new live questions with
the normal trial allowance. A new live generation consumes normal Credits;
this remediation run consumed none of the original tenant's Credits.

| Minutes | Show | Verified message |
|---|---|---|
| 0–1 | Sign in and Dashboard | Synthetic JO/JOD tenant, normal trial; no October 28 sales is expected. |
| 1–3 | Dashboard 7/30/90-day windows | Rounded revenue 3,448 / 16,203 / 47,600 JOD for October 28; windows move with the real date. |
| 3–4.5 | Products and inventory | Ten original products; 1L oil price 9.500, cost 6.200, stock 140; distinguish low/zero and fractional stock. |
| 4.5–6 | Demand | Ten actual forecasts; existing 1L oil 198 and loose za'atar 49 kg. Explain forecast restock versus raw low-stock counts. |
| 6–7.5 | Market / Industry Trends | Manual-or-unrecorded historical-source badges and neutral recorded-price wording. Explain that historical manual facts are not scraped/provider-verified prices. |
| 7.5–9 | Pricing history | Existing hold at JOD 9.500, three manual comparables; four covered products, six uncovered. No price application. |
| 9–10.5 | Reports / CSV | All 1,800 lines; revenue 85,892.200 and gross profit 33,257.500 JOD. Default financial-summary card is a shorter window. |
| 10.5–12.5 | Assistant | Ask “Which product has the highest total revenue across all our sales history?” Expected 4L oil, JOD 33,132, live report citation. Arabic equivalent passed. Existing document-policy answers/citations remain useful; semantic embeddings are still unavailable. |
| 12.5–14 | Marketing | Show verified grounded English/Arabic caption evidence, or generate a new draft with source facts and inspect it before publication. Do not reuse the old Phase 2 draft with invented origin. A review rejection is a real failure outcome, not a completed post. No new Phase 3 image generation is claimed. |
| 14–15 | Data connections / trial / Credits | Original completed imports, no verified commerce connection, unchanged trial cutoff November 11 at 08:57:14 +03:00. Explain remaining feature limitations. |

Remaining limitations: optional semantic embeddings/reranking, connected-store
acceptance, sentiment with sufficient actual reviews, discovery/scraping, PDF and
unexercised Phase 2 lifecycle cases remain outside this focused remediation.
Provider availability and broad open-ended language/factual accuracy are not
universally certified by these bounded passes.
