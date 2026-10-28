# Demo Data Seeding Phase 1 — Seed Truth Manifest

Date: **2026-10-28**, Asia/Amman. **Phase 1: PASS.**

Branch: `integration/keel-full-migration`. HEAD:
`65034f883c84228fc446aeaeef5315a55247d74b`. These seed utilities and this
manifest are local working-tree changes; no commit, push or deployment was made.
The pre-existing untracked `AGENTS.md` was preserved.

## Designated synthetic tenant and access

| Field | Value |
|---|---|
| Business | Zaytouna Meeting Demo — SYNTHETIC |
| Tenant | `fcf544d7-1174-43d9-a974-a0d705448200` |
| Login | `meeting-phase1@keel-demo.example` |
| Password | Private `.dev/fixtures/meeting-phase1/account.private.json`; never copy into Git or this report |
| Country / currency / calendar | JO / JOD / Asia/Amman |
| Frontend / API | `http://127.0.0.1:5173` / `http://127.0.0.1:8000` |
| Rights | Normal signup trial, source `trial`, status `trialing`, valid access |
| Actual trial cutoff | **2026-11-11 08:57:14 +03:00**; recheck before the meeting |
| Billing | No Stripe customer, subscription, Checkout or payment created by this task |

Signup and email verification used the running public API and the real code
delivered to this reserved recipient in local Mailpit. No verification mock,
privilege promotion, entitlement override, paid activation or trial reset was
used. The user has exactly this one workspace and cannot access platform-owner
administration (`/platform/me` returns 403).

This is a new tenant in the checkout-owned **local development database**,
isolated by normal authentication and PostgreSQL RLS. It does not run in a
separate application deployment. Existing tenants were neither reused nor seeded.

## Business inputs and actual counts

The fixed source period is **2026-05-01 through 2026-10-27**, 180 days. Each day
has two synthetic POS summary invoices, with five distinct product lines each.
Invoices have recorded historical `PAID` sales status; this is business input,
not evidence of a KEEL/Stripe subscription payment. Tax, shipping and discounts
are zero in this bounded fixture. Every product has a known acquisition cost.

| Record | Expected | Actual |
|---|---:|---:|
| Active bilingual products, unique SKUs | 10 | 10 |
| Closing inventory balances | 10 | 10 |
| Invoices | 360 | 360 |
| Invoice items | 1,800 | 1,800 |
| Canonical sales transactions | 1,800 | 1,800 |
| Completed business import jobs | 3 | 3 |
| Manually registered synthetic competitors | 3 | 3 |
| Manual competitor price observations | 24 | 24 |
| Products with current competitor comparison coverage | 4 | 4 |
| Uploaded knowledge documents, searchable | 3 | 3 |
| Verified external/store connections | 0 | 0 |
| Stripe payment records for this tenant | 0 | 0 |

Data Connections shows **three completed files in Recent Data Activity**: two
invoice XLSX imports and one closing-stock CSV. `/onboarding/sources` correctly
returns no connected external stores/APIs. No connector or synchronization success
was fabricated.

The stock file is a **closing physical snapshot after historical sales and
replenishments**, at Amman Demo Store on October 27. The import does not subtract
historical sales from it. No unrecorded purchase or stock-movement history is
asserted. Reorder level is 10 and safety stock is 5 for every product.

| SKU | Product | Price JOD | Cost JOD | Closing stock | Historical quantity sold |
|---|---|---:|---:|---:|---:|
| DEMO-001 | Extra Virgin Olive Oil 1L | 9.500 | 6.200 | 140 | 1,004 |
| DEMO-002 | Extra Virgin Olive Oil 500ml | 5.750 | 3.600 | 8 | 1,004 |
| DEMO-003 | Early Harvest Olive Oil 750ml | 12.500 | 8.100 | 0 | 1,004 |
| DEMO-004 | Olive Oil Tin 4L | 33.000 | 22.000 | 25 | 1,004 |
| DEMO-005 | Premium Za'atar Blend 250g | 3.250 | 1.400 | 320 | 1,004 |
| DEMO-006 | Loose Za'atar (per kg) | 9.800/kg | 4.500/kg | 4.5 kg | 251 kg |
| DEMO-007 | Sumac 200g | 2.600 | 0.950 | 180 | 1,004 |
| DEMO-008 | Seven Spices Mix 150g | 2.100 | 0.850 | 150 | 1,004 |
| DEMO-009 | Medjool Dates 1kg | 7.900 | 4.800 | 95 | 1,004 |
| DEMO-010 | Medjool Dates Gift Box 500g | 6.500 | 3.400 | 70 | 1,004 |

Inventory truth: **90% in stock, three low-stock products**, including one at
zero. The low-stock SKUs are DEMO-002, DEMO-003 and DEMO-006. Forecast-driven
restock advice is a separate calculation and can flag additional products.

## Expected business metrics, reconciled to actual data

| Metric, full history | Expected and actual |
|---|---:|
| Revenue | **JOD 85,892.200** |
| Cost of goods sold | JOD 52,634.700 |
| Gross profit | **JOD 33,257.500** |
| Gross margin | Approximately 38.72% |
| Sum of recorded quantities | 9,287.00 |

Gross profit is revenue minus quantity times current fixture cost; it is not net
profit. The quantity sum follows KEEL's aggregate display and combines pieces and
kg; it should not be interpreted as a homogeneous physical unit.

Dashboard calendar windows below include **October 28** in Asia/Amman. The
fixture has no October 28 sales, so Today is zero. Windows move with the real
date; source inputs remain fixed. `verify` recomputes expected windows.

| Window as of 2026-10-28 | Start inclusive | Revenue, expected = actual | Quantity sum, expected = actual |
|---|---|---:|---:|
| 7 days | 2026-10-22 | JOD 3,447.850 | 368.50 |
| 30 days | 2026-09-29 | JOD 16,202.850 | 1,756.00 |
| 90 days | 2026-07-31 | JOD 47,599.700 | 5,150.75 |

Dashboard rounds its 30-day revenue card to **JOD 16,203**. API money and report
rows were reconciled with Decimal arithmetic. All 1,800 invoice line facts
(SKU, business date, invoice number, quantity, unit price and total) and every
stock balance were compared with the separate generated source manifest.
Daily sales-trend sums also match the revenue cards.

The three competitors are **Demo Cedar Pantry**, **Demo Amman Grocer** and
**Demo Harvest Foods**, all labeled SYNTHETIC, with reserved `.example` URLs.
Each has two observations for DEMO-001 through DEMO-004, on October 13 and 26.
These are explicit manual scenario inputs, not scraped prices. The latest
three-competitor median matches each covered product's current price. The six
remaining products intentionally have no market-price evidence.

## Real derived outputs and honest boundaries

Opening Products during browser verification triggered its existing authorized
forecast refresh. The existing pipeline completed **10 real forecasts, zero
failures**: eight XGBoost and two baseline results. No forecast rows were inserted
by the seed utility. As observed on October 28, olive oil 1L forecasts 198 units
over the next 30 days; loose za'atar forecasts 49 kg. These are actual model
results, not fixed expected truth or a claim of forecast accuracy.

The application also generated **nine normal structured RAG summaries** through
its existing summary/indexing pipeline. They are distinct from the three
uploaded source documents. All three uploads are searchable, one chunk each:

- `company-and-delivery.md`: Amman only; JOD 2.000 delivery; free at a basket
  subtotal of JOD 30.000; 14:00 cutoff; Friday closed.
- `returns-and-stock.md`: unopened goods within seven calendar days with receipt;
  damaged goods reported within 48 hours; closing-stock semantics.
- `harvest-marketing-brief.md`: actual DEMO-001, price JOD 9.500; factual harvest
  post for Amman; no unsupported certifications, health claims or discount.

**Semantic embeddings: BLOCKED** by missing `sentence_transformers` in the
running environment. The existing keyword-search fallback indexed the documents
successfully. No package installation or model substitution was performed.

**Provider-backed RAG answers, marketing campaigns/images, pricing recommendation
generation and report-download acceptance: UNRUN in Phase 1.** There are zero
campaigns and zero conversation messages. Groq is configured, but configuration
alone does not certify provider access, approved cost rates or credit settlement.
Image capability is advertised; actual generation was not attempted. No external
market search, merchant store or payment acceptance is claimed.

## Reproduction, replay and evidence

From the repository root, use the configured checkout Python:

```powershell
.\.dev\venv\Scripts\python.exe tools/dev/seed_meeting_demo.py prepare
.\.dev\venv\Scripts\python.exe tools/dev/seed_meeting_demo.py seed
.\.dev\venv\Scripts\python.exe tools/dev/seed_meeting_demo.py verify
.\.dev\venv\Scripts\python.exe tools/dev/verify_meeting_demo_browser.py
.\.dev\venv\Scripts\python.exe -m unittest discover -s tools/dev/tests -p test_meeting_demo.py -v
```

The script delegates to the configured reusable Python when applicable. It is
limited to this checkout's generated local configuration and one reserved
identity; it accepts no arbitrary API URL, account or tenant override. Do not run
developer status/test/seed commands concurrently: they share a safety lock.

Inputs, random login password, tenant binding and exact reviewed import hashes
are retained in private `.dev/fixtures/meeting-phase1/`. Keep the account and
journal files: deleting them is not a supported reset. Existing mismatched
products, payload changes, missing trial access or conflicting reviews fail
instead of overwriting or granting rights. A retry reuses the normal trial,
existing SKU records, exact original confirmation, dated price facts and
content-addressed document uploads. Fixed-date source files are never extended
silently to the current day. Later manual edits may intentionally invalidate
seed verification; investigate before replaying.

Private evidence: `.dev/evidence/meeting-phase1/`:

| Evidence | Result |
|---|---|
| `backup.json` and referenced private backup directory | PASS: consistent exported snapshot, roles/config backup, restore into a separate retained DB; **139 table fingerprints match** |
| `idempotency.json` | PASS: complete seed replay leaves **21 tenant business/usage tables unchanged**, including receipts, files and allowance counters |
| `verification.json` | PASS: **58 reconciliation, isolation and preservation checks**, plus successful feature API reads |
| `browser.json` and `browser-*.png` | PASS: **18 checks**, English 1440px and Arabic RTL 390px, real UI login/API, no response mocks or explicit generation button presses |
| Focused unit suite | PASS: **3 tests** for stable valid source payloads, exact confirmation replay and unresolved-review refusal |
| `dev.ps1 db-check` | PASS: **146 migrations**, restricted login/role checks, pgvector, **120 FORCE RLS tables** |
| `dev.ps1 status` | PASS: API/Redis/database ready, frontend and all eight worker readiness checks, four normal infrastructure containers healthy |

All **109 tenant-owned tables for the 11 pre-existing tenants** match the
pre-seed restore. Protected local configuration and `.env.example` hashes match.
Native `ceopro_app` queries cannot cross the tenant boundary, including the
populated direction from an unrelated context into this demo. No RLS/role policy,
application source, migration, provider configuration or customer record was
changed. The restore database and private backup are retained; no restore/drop
was performed against the normal development database.

The running process ledger still identifies implementation revision `dd9bd4d`;
HEAD `65034f8` is the documented report-only follow-up. Services were preserved,
not restarted. Existing Stripe Test Clock configuration was preserved without
creating or advancing any Stripe resource.

Changed files: `tools/dev/seed_meeting_demo.py`,
`tools/dev/verify_meeting_demo_browser.py`,
`tools/dev/tests/test_meeting_demo.py`,
`backend/scripts/demo_companies/README.md`, and this manifest.

## Phase 2 manual feature-testing handoff

Sign in to the designated tenant above, using its private password file. Recheck
trial validity and run `verify` before the meeting. Use these coherent paths:

| Feature / route | Manual check and expected outcome |
|---|---|
| Dashboard `/dashboard` | Select 7/30/90 days; compare against the current-date manifest. October 28 has zero Today sales. Check revenue chart/tooltips and forecast/restock cards after refresh. |
| Products `/products` or `/catalog` | Find DEMO-001 by name/SKU; ten bilingual products, costs and JOD prices; no duplicate imported products. Inspect Arabic/RTL detail views. |
| Inventory, product detail / `/demand` | DEMO-003 is out; DEMO-002 has 8 and DEMO-006 has 4.5 kg. Distinguish the three raw low-stock balances from forecast-driven restock advice. |
| Data Connections `/connect-data` | Three completed source imports and no claimed external connection. Preview a file only if testing review; avoid a new confirmation identity for these already-posted invoices. |
| Demand `/demand` | Ten real forecasts; refresh progress should finish without failures. Inspect DEMO-001's actual forecast, history, method and confidence; model quality/accuracy acceptance remains a separate check. |
| Competitors `/market` | Three labeled manual competitors; inspect dated price histories for DEMO-001. `/market/competitors` intentionally redirects here. No discovered/scraped scan is asserted. |
| Pricing `/pricing` | Four products have exact manual evidence, six do not. Generate one recommendation through the normal action and inspect evidence/freshness/fallback and usage; no target recommendation price is pre-seeded. |
| Reports `/reports` | Full history contains 1,800 lines totaling JOD 85,892.200; visible table is paginated. Download CSV/JSON through the UI and reconcile dates, totals, gross profit and normal report allowance/idempotency. No completed export artifact is pre-seeded. |
| Assistant `/ai-advisor` | Ask “What is our free-delivery threshold?” Expected fact: JOD 30.000, cite the uploaded policy. Ask about seven-day returns and highest-revenue product (4L oil, JOD 33,132.000 full history). Verify actual citations, calculations, persistence and credit settlement. No canned answer exists. |
| Marketing `/marketing` | Select DEMO-001 and use the harvest brief. A valid unsubmitted request is in `.dev/fixtures/meeting-phase1/marketing-request.json`. Generate one real post, then separately test image creation if authorized/configured; verify persisted output and accounting. No campaign/image is pre-created. |

For provider failures or missing approved financial configuration, record
**BLOCKED** with the actual reason; do not seed an answer, invent costs, grant
credits or fake success. Phase 2 may consume the tenant's normal trial allowances.
Do not use a payment or plan change to make the meeting fixture appear ready.
