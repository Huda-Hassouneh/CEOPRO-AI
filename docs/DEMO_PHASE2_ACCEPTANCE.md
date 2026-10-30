# Phase 2 — Real customer feature acceptance

Date: **2026-10-28, Asia/Amman**. Overall: **PARTIAL**. The bounded meeting
sequence below is rehearsed; this is not full feature or production acceptance.
There are real failures in business-question scope, marketing factuality and
automated report tests, plus unverified external integrations.

## Verified checkout and runtime

- Checkout: `E:\KEEL START\CEOPRO-AI`, branch `integration/keel-full-migration`.
- Starting and final HEAD: `697561a8aef37a4255ac0a774df9714beb67c2d6`.
- Configured frontend: `http://127.0.0.1:5173`; API: `http://127.0.0.1:8000`.
- Initial and final status: API database/Redis readiness OK, all eight workers
  ready, frontend running, four normal infrastructure containers healthy.
  API process identifies this HEAD; workers/frontend ledger identifies
  `dd9bd4d37062ae3284e530456e64a5b58be5ae49`. Frontend Vite serves current
  sources, but the old launch revision must not be reported as a full restart.
- Synthetic tenant: `fcf544d7-1174-43d9-a974-a0d705448200`,
  `meeting-phase1@keel-demo.example`. Password remains in the private Phase 1
  account file. Normal Plus trial, access valid, cutoff
  **2026-11-11 08:57:14 +03:00**. No paid activation was performed.

Read `AGENTS.md`, root README, `DEMO_SEED_PHASE1.md`,
`RAG_ASSISTANT_503_FIX.md`, recovery guidance and the relevant existing
React/API/service implementations before testing. Existing local changes were
preserved. No reseeding, RAG remediation, installation, application patch,
migration, commit, push or deployment was performed.

## Acceptance matrix

PASS below means the stated outcome passed; PARTIAL and BLOCKED explicitly
limit the claim. API reads alone are not end-to-end acceptance.

| # | Capability | Result | Evidence and remaining scope |
|---|---|---|---|
| 1 | Dashboard analytics | **PASS**, bounded | Real UI 7/30/90-day switching displays rounded JOD 3,448 / 16,203 / 47,600. Baseline API reconciliation matches JOD 3,447.850 / 16,202.850 / 47,599.700 and daily trends. Today is zero. English desktop and Arabic mobile render. |
| 2 | Product management | **PARTIAL** | Disposable bilingual manual product created, price changed to 3.25 and reread, then deleted; detail returns 404 and only original ten active SKUs remain. Original product rows unchanged at immediate post-test snapshot. Background competitor classification retained an effect from the temporary eleventh product; the subsequent owner-approved refresh corrected it to 40% overlap for all three competitors. |
| 3 | Inventory | **PASS**, bounded | Disposable stock updated to 4.5 and reread; negative stock rejected with 422. Original ten stock rows unchanged at immediate post-test snapshot. Baseline reconciles 90% in stock and three low-stock SKUs: DEMO-002, 003, 006. |
| 4 | Data connections / document extraction | **PARTIAL** | Three existing completed imports visible in real UI; three uploaded documents searchable; no external sources falsely connected in API. No new business import confirmation or fresh OCR/extraction run. Original import source inputs were not replayed. |
| 5 | Demand prediction | **PARTIAL** | Ten existing actual forecasts read; demand UI displays aggregate 1,817 next-30-day units and restock advice. DEMO-001 shows 198; loose za'atar 49 kg. Existing page effects may refresh forecasts. No independent accuracy/backtesting certification or explicit refresh-to-completion acceptance in this phase. |
| 6 | Competitor management | **PARTIAL** | Three manual synthetic competitors and 24 dated manual price observations; four covered products and six without comparison. Original price facts unchanged. Discovery, scraping, source approval and real competitor CRUD not accepted. Owner-approved canonical reclassification passed after disposable product deletion: three refreshed, 40% overlap each, zero demotions, tracking unchanged. |
| 7 | Market intelligence / customer perception | **FAIL** for provenance wording; **BLOCKED** for sentiment conclusions | Structure API correctly counts three businesses and returns manual prices. `/market/trends` says businesses were “found by your scans” and prices were published, although this fixture is manual and no website was read. Market analysis is null; zero reviews; valid BUSINESS sentiment request returns UNKNOWN / LOW_SAMPLE_SIZE, minimum 10. No sentiment conclusion or external market-research acceptance. |
| 8 | Pricing recommendations | **PARTIAL** | Real DEMO-001 decision: hold 9.500 JOD; three competitors, market average/median 9.500, confidence 0.55. Exact idempotent retry and persisted history passed; history modal opens in browser. No product price applied. Uncovered-product decision, accept/reject feedback and stale/currency edge cases not real-provider accepted here. |
| 9 | RAG Assistant | **PARTIAL**, with **FAIL** | Prior document answers/history/citations remain available; persisted citation panel reopened without generation. New real all-history question identifies 4L oil but substitutes a 90-day JOD 18,315 summary for expected all-history JOD 33,132. It states the 90-day period, but does not fulfill the requested scope. HTTP 200 is not a factual acceptance pass. Semantic embeddings/reranking remain BLOCKED. |
| 10 | Smart alerts | **PARTIAL** | Real alerts include out-of-stock early-harvest oil, 500ml oil and loose za'atar with product links and forecast-based restock quantities. UI bell visible. Acknowledgement, delivery, preferences and scheduled notification lifecycle not exercised. Nine forecast restock flags are distinct from three raw low-stock balances. |
| 11 | Marketing copy / images | **PARTIAL**, with **FAIL** | Real Groq copy persisted; real AI image completed, stored, authenticated download decoded at 768×768, and reopened in UI. Image is a generic unbranded oil-bottle illustration, not verified product photography. Copy invents “crafted from Amman's finest olives” / “bottled right here in Amman”; supplied product facts do not support those claims. Do not present it as approved factual copy. No publishing, bulk jobs, reference-photo fidelity or background-removal acceptance. |
| 12 | Billing / subscriptions / Credits | **PARTIAL** | Trial/usage UI works; tenant's four protected billing/assignment fingerprints match pre-RAG baseline. Credits reconcile to ledger with zero reserved. No Checkout, payment, plan change, webhook or Test Clock action. Global preservation cannot be certified: unrelated billing drift observed during window. |
| 13 | Shopify / WooCommerce | **BLOCKED** | No verified connected stores in this tenant. No store credentials, authorization, sync or write-back tested. A configured worker is not commerce acceptance. |
| 14 | Reports / exports | **PARTIAL** | Real CSV and JSON each contain all 1,800 lines: exact revenue 85,892.200 and gross profit 33,257.500 JOD. UI CSV download independently reconciled. Two explicit API export identities each have one metered key with replay flag; retry does not create another key. 365-day financial summary matches totals with 100% cost coverage. PDF, Arabic export content, date filters and pagination interactions not accepted here. Twelve existing mocked report tests failed; see below. |
| 15 | Platform administration | **PARTIAL** | Real demo Tenant Owner receives `/platform/me` 403; unauthenticated catalog receives 401; native restricted-role RLS checks hide foreign products and populated demo invoices from unrelated context. No Platform Owner mutation or full staff-role matrix was exercised. |

## Preservation and accounting

**PASS: original financial business facts.** Immediate before/after snapshots
match for the original ten product rows, their inventory, 360 invoices, 1,800
invoice items, 1,800 transactions and 24 competitor prices. Final read-only
reconciliation again matches invoice/item/transaction/price fingerprints. Both
download formats reconcile revenue **JOD 85,892.200** and gross profit
**JOD 33,257.500**; only ten original active SKUs remain. The disposable product
was soft-deleted through the API; normal audit/soft-delete/derived artifacts are
not purged from the database.

**PARTIAL: full seeded-row preservation.** `tenant_competitors` fingerprints
changed, while competitor count and price facts did not. Current derived fields
initially showed 0.3636 product overlap and 36% classification reasoning, consistent with
four matched products over the temporarily present eleven-product catalog.
Existing product creation queues discovery; classification code persists the
ratio and timestamps. A post-deletion refresh was initially blocked, then
explicitly approved and completed; see the follow-up below. The initial evidence
does not capture a full before-row column diff, so attribution to individual
columns is limited. Do not claim every seeded row remained byte-identical.

**PASS: approved classification cleanup, October 28 at 10:17:56 +03:00.**
Following explicit owner approval, the authenticated demo tenant called the
existing `POST /competitors/reclassify` once. All three competitors now have
**0.4000 / 40% product overlap**, reflecting four matches among ten active
products. Zero demotions; competitor IDs, tracking and global competitor rows
are unchanged. Normal derived classification reason, timestamp, confidence
fields and evidence ID were refreshed; no historical values were overwritten
through direct SQL. Private full competitor-row snapshots were saved and their
serialization verified before the action.

All **10 cleanup checks passed**: three reclassified, none demoted, correct
overlap, unchanged business-table fingerprints, unchanged global billing/Credits
fingerprints, unchanged other-tenant fingerprints, unchanged global competitor
rows, unchanged revenue/profit, unchanged competitor IDs and unchanged tracking.
Revenue remains JOD 85,892.200 and gross profit JOD 33,257.500. This short
cleanup-window preservation result does not negate the earlier Phase 2 global
drift finding. Evidence: private `approved-refresh-result.json`,
`approved-refresh-response.json`, `approved-refresh-before.private.json` and
`approved-refresh-after.private.json` under `.dev/evidence/meeting-phase2/`.
HEAD remains `697561a8aef37a4255ac0a774df9714beb67c2d6`; runtime readiness
was rechecked successfully before cleanup; no restart, push or deployment.

**PASS: demo billing preservation.** Demo `billing_subscriptions`,
`billing_payments`, `billing_trials` and `tenant_plan_assignments` match the
retained pre-RAG fingerprints. Phase 2 called no billing mutation endpoint.

**FAIL: database-wide unchanged assertion.** The first Phase 1 verifier already
found unrelated company/subscription/payment/assignment drift and a changed
private integration-file hash versus the old backup, before acceptance writes.
During Phase 2, non-demo chat/document/usage fingerprints also changed. Global
billing fingerprints matched immediately after the main acceptance actions,
but the later final check found changes in `tenant_plan_assignments`,
`billing_webhook_events`, `billing_payments`, `billing_trials`,
`billing_customers`, `billing_subscriptions`, `billing_checkout_attempts`.
These global changes were not caused by a billing API call from these scripts;
their external/background origin is not established by this evidence. Existing
customers and billing records were not inspected for contents, edited or
restored. A quiet isolated environment is required to certify global preservation.

**PASS: metered Groq settlement.** Demo AI Credits rose from 0.1322 to 0.1993:
**0.0671 consumed in this phase**. Metered cost rose from USD 0.001321 to
0.001990: **USD 0.000669** additional. Seven total ledger entries, unique
idempotency keys, balance equals settled ledger under existing six-decimal
cost rounding, **zero outstanding reserved Credits**. The image path records
the application's free external-image service, not a new paid-image cost rate;
no provider invoice verification is claimed. Normal report/token/storage usage
and derived evidence are expected additions, not resets.

The new campaign `54044e6d-a4ba-4564-ba96-37e3a43e5ba6` is a disposable
acceptance/demo artifact, retained to reopen its real generated image. It is
not published or approved copy. The new RAG session and pricing evidence are
also retained as actual test outputs. No original campaign existed to overwrite.

## Verification evidence

Private evidence: `.dev/evidence/meeting-phase2/`; keep responses, exports,
screenshots and snapshots private. No credentials or tokens are in this report.

| Check | Result / evidence |
|---|---|
| Existing baseline verifier | **FAIL overall**, 58 checks; business counts/metrics pass, historical global preservation/config hashes fail as described. Original `.dev/evidence/meeting-phase1/verification.json` now records this current verification, not the historical Phase 1 run. |
| Real API actions | `checks.json`, individual response files, `before.json`, `after.json`, `run.json`; distinguish HTTP checks from semantic failures above. |
| Report reconciliation / accounting / RLS | `reconciliation.json`, `accounting.json`, `final-billing-preservation.json`; real native `ceopro_app` password/context, no mocked provider responses. |
| English / Arabic real browser | **PASS: 24 route checks**, English 1440px and Arabic RTL 390px, no response mocks; `browser.json`, `browser-*.png`, private body text. Route/content/overflow checks do not imply all controls were tested. Demand mobile table is narrow; no pixel-perfect claim. |
| Exact meeting interactions | **PASS: 12 checks in 33.4 seconds** of automated UI execution, excluding narration; `rehearsal.json`, `rehearsal-summary.json`, `rehearsal-*.png`. No new generation requests. This is a rehearsal of the actions, not a measured 15-minute spoken presentation. |
| Focused isolated backend | **FAIL: 51 passed, 12 failed**, no skipped tests reported. `.dev/evidence/tests/c14831a21759/backend.log`, `backend.xml`, `migrations.log`, `run.json`. All failures are `test_reports.py` mocked HTTP cases returning capability-check 403 before their expected handler outcomes; exact fixture/root-cause correction remains unimplemented. Real API/UI downloads passed independently. |
| Test database security | **PASS:** separate `keel_billing_test_devc14831a21759`, 146 migrations, pgvector, restricted password login, 120 FORCE RLS tables; test services stopped, DB retained. No normal DB migration. |
| Developer tooling wrapper | **PASS: 52 tests** in backend and frontend commands. |
| Frontend current checkout | **PASS:** `dev.ps1 test --suite frontend` exit 0: tests, ESLint and production build. Existing chunk-size/dynamic-import build warnings remain. This rerun is distinct from the earlier RAG report's 229-test result. |
| Acceptance utility validation | **PASS:** Python compilation and `git diff --check`. |
| Final runtime | `final-runtime.txt`: healthy normal runtime; no normal service restart. |

The initial sandbox could not access Docker's named pipe/private-state ACLs;
approved elevated checks succeeded. This was not a Docker outage. An exploratory
unsupported `subject_type=COMPANY` sentiment call returned 500; the supported
BUSINESS request then returned the truthful empty-data outcome. Invalid-input
error handling is an additional API issue, separate from customer sentiment
acceptance.

## Verified 15-minute meeting sequence

This sequence uses working paths and persisted actual outputs. It deliberately
does not depend on fresh provider latency. Rehearsed actions are identified by
the evidence above; the minutes below allocate presenter explanation time.

Before the meeting: run `dev.ps1 status`, confirm the same tenant and valid trial,
and use the existing private password. Recompute dashboard expectations if the
date changes. Do not rerun seeding or the paid acceptance driver. Keep the
verified local CSV and image available if an external provider is unavailable.

| Time | Presenter action | Verified result / what to say |
|---|---|---|
| 00:00–01:00 | Sign in to the designated tenant; open `/dashboard`. | Synthetic Jordanian JOD business, normal trial. Today's zero is expected; the source period ends October 27. |
| 01:00–03:00 | Switch 7, 90, then 30 days on Dashboard. | Rounded revenue 3,448 / 47,600 / 16,203. Explain date windows, revenue versus profit, and the genuine 1,817-unit forecast. |
| 03:00–04:30 | Open `/products/2ebeca56-ac15-413c-bd90-64d1a337dae4` (1L oil), then `/products` for stock context. | Price JOD 9.500, cost 6.200, stock 140. Explain the separately verified out-of-stock DEMO-003 and fractional za'atar stock; make no edits. |
| 04:30–06:00 | Open `/demand`; point out low/zero stock and forecast/restock cards. | Ten actual forecasts; 1L oil 198 and loose za'atar 49 kg. Explain why nine forecast restock flags differ from three raw low-stock products. Do not promise model accuracy. |
| 06:00–07:00 | Open `/market`. | Three explicitly synthetic manual competitors. Say all 24 price inputs were manual scenario observations, not scraped. Avoid the misleading scan/publication narrative on `/market/trends`. |
| 07:00–08:30 | Open `/pricing`; 1L oil row → Recommendation history. | Saved “Hold price at 9.500 JOD,” three competitors, confidence 0.55. Four products have exact comparison coverage; six lack it. No price applied. Do not refresh classifications or trigger collection. |
| 08:30–10:30 | Open `/reports`; download Export CSV. | Real download, all 1,800 lines. Open retained full-history CSV if needed: revenue 85,892.200, gross profit 33,257.500. Visible Financial Summary defaults to 30 days: revenue 16,202.85, profit 6,276.65; do not label those full-history totals. |
| 10:30–11:30 | Open `/connect-data`. | Three completed original imports and searchable documents; no connected Shopify/WooCommerce store claimed. Do not reconfirm historical invoices. |
| 11:30–13:00 | Open `/ai-advisor`; select the existing successful delivery/returns conversation and expand a citation. | Persisted document-grounded answer and reference panel work. Free delivery threshold JOD 30; delivery JOD 2; seven-day unopened returns with receipt. If a different session is selected, choose the prior document conversation from history. All-history financial questions remain a known scope failure; use Reports for exact totals. No fresh send is needed. |
| 13:00–14:00 | Open `/marketing`; open saved Extra Virgin Olive Oil 1L campaign. | Reopened real generated image. Identify it as illustrative; copy requires factual review because of unsupported origin claims. Do not publish or regenerate. |
| 14:00–15:00 | Open `/billing`; show trial and Credits; describe remaining acceptance gaps. | Trial through November 11; approximately 0.2 / 111 AI Credits used, no outstanding reservation at verification. No payment or plan action. Mention stores, sentiment evidence and semantic embeddings as unavailable/unverified. |

If asked to generate live: a new action may consume normal trial allowances and
may hit provider rate limits; the reliable meeting sequence above uses actual
persisted outputs. Do not treat configuration or cached answers as a fresh
provider success.

## Remaining work and approval boundary

Prioritize fixes/acceptance for RAG period fidelity, unsupported marketing claims,
manual-market provenance wording and report test capability fixtures. Continue
external store, extraction/OCR, sentiment, alert lifecycle, PDF/date-range and
full role-matrix acceptance only with the required disposable infrastructure and
real evidence. These are findings, not changes silently included in this task.

Automatic approval review initially **rejected** a proposed
`POST /competitors/reclassify` cleanup. Its reason: reclassifying existing seeded
competitors exceeds disposable-record authorization and conflicts with seeded
dataset preservation. That rejected POST did **not** execute; no workaround
was used. The owner subsequently explicitly approved this exact refresh. The
approved canonical API action then executed and passed all 10 cleanup checks
above. The stale-overlap cleanup is complete; the other acceptance failures
and limitations remain open. Overall Phase 2 status remains **PARTIAL**.

Changed files for this phase: this report,
`tools/dev/accept_meeting_phase2.py`, `verify_meeting_phase2_results.py`,
`verify_meeting_phase2_browser.py`, `rehearse_meeting_phase2.py`.
The acceptance driver refuses replay once evidence exists; do not delete its
guard files to retry paid actions. Private evidence is intentionally untracked.
All pre-existing local Phase 1 changes remain untouched.
