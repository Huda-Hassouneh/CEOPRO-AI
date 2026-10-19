# Competitor data completeness — root causes and fix plan

Status: Phases 1-3 are built on `main` (ledger, PROFILE / SOCIAL_LINKS / REVIEWS / NEWS / COMMENTS facets, retry endpoints, worker). Section 8 below is the v2 roadmap and its progress log (menus + OCR, PRICES facet, deeper loads). Sections 1-7 are the original plan, kept for the reasoning.
Findings below come from reading the code; Phase 0 confirms them against the live DB before any build.

## 1. The problem in product terms

A competitor row today is a *name + website + score*. Everything a CEO actually acts on —
their prices, what customers say, what they post — is absent for most rows, and when it
is missing the owner cannot tell **why** or **do anything about it**.
Target outcome: every listed competitor shows a **data-completeness panel** (Profile · Prices ·
Reviews · Social) where each facet is either filled, or says *why not* and offers **Retry**.
Retrying only adds or upgrades data — it never wipes what we already have.

## 2. Root causes (verified in code)

| # | Root cause | Evidence | Effect |
|---|------------|----------|--------|
| R1 | **Collection needs `policy_status = ALLOWED`, and discovery can never produce it.** `ALLOWED` requires `terms_evidence`; automated discovery never has any, so every new source lands `RESTRICTED`. | `discovery.py` `evaluate_candidate` / `register_tenant_scoped_competitor`; `policy.py` L85-91; `discovery_worker._enqueue_allowed` only enqueues `ALLOWED`; `enqueue.py` L69 and `cli.py` L21 hard-fail otherwise | Only a source a human approved earlier gets prices. This is why exactly **one** competitor has prices. |
| R2 | **Nothing ever collects reviews or social for a discovered competitor.** The Places review spider and the three social spiders only run for a hand-created `data_sources` row with credentials; discovery creates none. `social_cross_reference` and `get_social_profiles_cached` are called only from `scripts/run_e2e_pipeline.py`. | grep: no production caller | Zero review / social / sentiment data, regardless of policy. |
| R3 | **Places key is never passed in production.** `discover_for_tenant` calls `discover_domain_level_competitors_for_tenant(conn, tenant_id, actor)`; its `google_places_api_key` defaults to `None` and the function has no env fallback. | `discovery_worker.py` L90, `tenant_discovery.py` L253/L334 | Nearby-Places discovery, ratings, phone, address, coordinates silently skipped. Web-search hits carry no details at all. |
| R4 | **Businesses without a website are dropped.** `discover_nearby_places` `continue`s when Place Details has no `website`. | `places_nearby_discovery.py` ("no real, resolvable domain") | Small restaurants / salons that live on Instagram or Google Maps are never found. `global_competitors.website_url` is nullable, so the schema allows them. |
| R5 | **Review/price collection is keyed on product mappings.** `load_scrape_targets` joins `competitor_product_mappings`; a domain-level competitor has none. `map_products_on_domain_competitor_site` only runs for *confirmed* competitors and only finds JSON-LD/sitemap products. | `data_access.py` L138-170, `tenant_discovery.py` L367 | Service businesses (restaurants, clinics) and non-product sites have nothing to attach prices or reviews to. |
| R6 | **Social handles found are thrown away.** `extract_social_profiles` returns the competitor's own Facebook/Instagram links from its homepage but nothing persists them. | `direct_search.py` L211; only `run_e2e_pipeline.py` uses it | No target for the Apify / ScrapeCreators / transcript collectors even when credentials exist. |
| R7 | **Failures are invisible and terminal.** `discover_*` swallow errors into `[]`; a failed job dead-letters after 3 tries in Redis; the dashboard has no field for "why empty". Quota exhaustion (100/day Custom Search) looks identical to "no results". | `web_product_discovery.py`, `worker.py`, `competitors.py` | Owner sees blanks, engineers see nothing. No path to "try again with a better option". |
| R8 | **Fragile extraction.** Generic collector reads only JSON-LD; JS-rendered shops, menu PDFs, and "contact for price" pages yield nothing; a 0.82 name-match gate rejects Arabic/transliterated names; robots.txt fetch failure → `RESTRICTED`. | `collectors.py`, `google_places.py` L25, `discovery._fetch_robots_allows` | Silent partial data. |
| R9 | **Social value lives in captions, images and comments, which we do not read.** Captions/transcripts only via a hand-configured Apify actor; no image/OCR step; TikTok excluded. | README collectors section | Pricing, promotions and menu items posted only as images/videos are missed. |

## 3. Design — "Enrichment" as a first-class, retryable pipeline

### 3.1 Coverage ledger (new table, additive migration)
`competitor_enrichment(tenant_id, global_competitor_id, facet, status, reason_code, reason_detail, provider, attempts, items_found, data_confidence, last_attempt_at, next_retry_at, updated_at)`,
unique on `(tenant_id, global_competitor_id, facet)`, RLS identical to `tenant_competitors`.

* `facet` ∈ `PROFILE | PRICES | REVIEWS | SOCIAL_LINKS | SOCIAL_CONTENT`
* `status` ∈ `PENDING | RUNNING | SUCCEEDED | PARTIAL | FAILED | BLOCKED | NOT_APPLICABLE`
* `reason_code` (the "why", shown to the owner): `NO_WEBSITE, ROBOTS_DISALLOWED, TERMS_UNREVIEWED, NO_CREDENTIALS, QUOTA_EXHAUSTED, PROVIDER_ERROR, NO_MATCH, NO_STRUCTURED_DATA, JS_RENDERED, NO_PRODUCTS_IN_COMMON`
* `data_confidence` 0-1 per facet (how sure we are the data belongs to *this* business: place_id match = 1.0, fuzzy name ≥0.82 = 0.8, search hit = 0.5). Feeds the existing confidence breakdown rather than replacing it.

### 3.2 Facet collectors (each idempotent, additive, independently retryable)

| Facet | Source (in order) | Fixes |
|-------|-------------------|-------|
| PROFILE | Places Details by `place_id` (address, phone, hours, rating, price_level, website, editorial summary) → website `<meta>`/JSON-LD `LocalBusiness` | R3, R4 |
| SOCIAL_LINKS | competitor homepage (`extract_social_profiles`), Places website, Custom Search `site:instagram.com "<name>"` → store verified handles | R6 |
| REVIEWS | Places Details `reviews` (official API, 5 newest) → business-level `reviews` rows (`subject_type='COMPETITOR'`, already supported, no mapping needed) | R2, R5 |
| PRICES | structured data on mapped product pages (existing); **menu / price-list page** discovery for service businesses; price from social captions (below) | R1, R5, R8 |
| SOCIAL_CONTENT | existing `social_data_provider` → `video_transcript_provider` → caption + image text via the platform's existing LLM client | R2, R9 |

All text passes the existing `content_safety.scan_external_text`; all writes use COALESCE/upsert so a retry *adds* fields and *raises* confidence, never blanks them.

### 3.3 Fixing the approval wall (R1) — needs a product decision
Three classes, three rules:
1. **Official API sources (Places)**: approve **once per platform** by an operator (recorded `approval_reference`), then every tenant's Places call is `ALLOWED`. No per-competitor human step.
2. **Competitor's own public site** (robots.txt allows, public JSON-LD): proposed **tenant-admin one-click "Approve collection"** on the competitor card (records `approved_by`, `approval_reference`, audit log — reuses `record_policy_decision`). Until clicked, status is `BLOCKED/TERMS_UNREVIEWED` with that button visible.
3. **Social platforms**: only through the licensed provider (never direct), gated on provider credentials existing → otherwise `NO_CREDENTIALS`.

### 3.4 Retry & API surface (additive; existing contracts unchanged)
* `POST /competitors/{id}/enrich` body `{facets?: [...], force?: bool}` → enqueues on new stream `market.enrichment.requested` (same attempt/dead-letter/reclaim pattern as `discovery_worker.py`); returns 202 + current ledger.
* `GET /competitors/{id}/data-status` → ledger rows.
* `POST /competitors/enrich-failed` → retry every `FAILED/PARTIAL` row (bulk "Retry all").
* `/dashboard/competitors` rows gain **additive** `data_completeness: {score, facets: {facet: {status, reason_code, can_retry, last_attempt_at, confidence}}}`. No existing field renamed or removed.
* Automatic: enrichment is enqueued at end of `discover_for_tenant`, plus backoff retries for `PROVIDER_ERROR/QUOTA_EXHAUSTED` via `next_retry_at` (daily scheduled sweep; quota resets).
* Retry is deduped (one in-flight job per competitor+facet) and rate-limited per tenant.

## 4. Phases

**Phase 0 – Confirm (½ day, read-only).** SQL/CLI report per competitor: has place_id/rating? mapping rows? data_sources policy_status? prices/reviews/social counts? Confirms R1–R6 and sizes the gap. Also check `GOOGLE_PLACES_API_KEY` reaches the *discovery* worker container (`docker-compose.yml` L341 is set on one service only).

**Phase 1 – Foundation + quick wins.**
migration (ledger + `google_place_id`), pass Places key from env (R3), keep website-less Places hits keyed by `place_id` (R4), persist social links (R6), `data_completeness` in dashboard, `data-status` endpoint.

**Phase 2 – Retry pipeline.** enrichment worker + stream, `POST …/enrich`, bulk retry, scheduler for backoff, reason codes everywhere failures are currently swallowed (R7).

**Phase 3 – Data depth.** Places reviews as business-level rows (R2/R5), menu/price-page extraction (R8), approval button + platform-level API approval (R1), per-facet `data_confidence` into the confidence breakdown.

**Phase 4 – Social content.** wire `social_data_provider` / transcripts from stored handles, caption + image text extraction, price/promo mining from posts (R9); cost ledger integration so spend is bounded.

## 5. Compatibility checklist (verified before each change)

* Migrations are additive (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`) with RLS + `ceopro_app` grants, logged in `CONTRACT_CHANGELOG.md` and `AI_PLAN_AND_CONTRACT_UPDATES.md` (as the last two commits did).
* `/dashboard/competitors`: only new keys added; `summary_line` and existing keys untouched; add test to `test_dashboard_competitors_integration_db.py`.
* `reviews` constraints: `chk_review_subject_consistency` (COMPETITOR ⇒ `competitor_id` set, `product_id` NULL) and `chk_review_collection_method` (`PUBLIC_API`) — business-level Places reviews fit; no mapping needed. `save_market_record` still requires `mapping_id` for `market_observations`, so price/page observations keep going through mappings.
* Pipelines: `pipelines.py` already treats `mapping_id` as optional; do not relax `save_market_record`.
* RLS: every new query run under the restricted `ceopro_app` role, with a cross-tenant test like `test_competitor_relevance_rls_integration_db.py`.
* Idempotency: re-running an unchanged enrichment writes no duplicate reviews/evidence (reuse the dedup used in `competitor_classification`).
* No direct Instagram/Facebook scraping; robots.txt and `content_safety` stay in force; paid calls respect `cost_ledger`.
* Run the full existing suites (`src/market_scraper/tests`, `src/ai/tests`) plus new unit + live-DB tests per phase; fail the phase if any pre-existing test changes.

## 6. Risks / honest limits

* Places returns **5 reviews max** per place and bills "Atmosphere" fields separately — fine for sentiment signal, not a full review archive. Fuller review depth needs the paid provider (cost decision).
* Apify/ScrapeCreators/transcript actors have **unverified field names** (README says so); Phase 4 must start with a real sandbox run.
* Image text extraction needs an LLM-vision or OCR dependency that does not exist in the repo today; scoped as optional within Phase 4.
* Phase 0 may show some of R1–R6 are less severe than inferred (e.g. a key already set elsewhere).

## 7. Decisions needed from product

1. **Approval model** (3.3): OK to add tenant-admin one-click approval for competitor websites, and operator-level one-time approval for Places?
2. **Budget**: acceptable monthly spend for Places Details + social provider per tenant (drives default depth and the retry cap)?
3. Which **social providers/credentials** exist today (Apify? ScrapeCreators?) — decides whether Phase 4 can be verified live.


## 8. v2 roadmap - menus, prices, OCR, deeper loads (branch `feat/competitor-completeness-v2`)

Why: after PR #58 and the enrichment work, the biggest remaining gaps for "optimum competitor details" are
(a) prices published only as menu pictures / PDFs, (b) PRICES and SOCIAL_CONTENT are shown in the completeness
panel but have no Retry behind them, (c) every refresh is the same shallow read - no way to "load more",
(d) a refresh that reads less than before silently deletes richer data (violates "retry only adds"),
(e) nothing tells the owner which numbers are verified versus guessed.

| # | Change | Status |
|---|--------|--------|
| V1 | Read menu PDFs and pictures (text layer, else tesseract OCR ara+eng) into the price facts: `market_discovery/menu_media.py`, wired into `intel.collect`. Facts tagged `extracted_by`, lower confidence; corroboration (`also_seen_in`) and conflict flag (`conflicts_with_price`). | DONE |
| V2 | PRICES facet becomes retryable: `POST /competitors/{id}/enrich {facets:["PRICES"]}` re-reads the site (+menus) and writes the ledger with a specific reason (JS-rendered, robots, unreachable, no price published, menu is a picture and OCR is missing). | DONE |
| V3 | "Load more": `depth` = `standard` / `deep` on the enrich request - deep reads more pages, items and menu files. | DONE |
| V4 | Additive guarantee: a re-read that could not read menu files (OCR missing, fetch failed) keeps the menu-derived facts from the earlier read instead of deleting them. | DONE |
| V5 | Completeness panel: PRICES prefers the ledger's specific reason over the generic derived one; reports site-published prices even when none is matched to a product yet. | DONE |
| V6 | Owner verification of a fact (confirm / correct / reject) that survives re-reads - needs a table (`competitor_intel_review`) keyed by competitor + normalized name + source. | OPEN (design below) |
| V7 | SOCIAL_CONTENT collector: captions and post pictures from stored handles through the licensed provider, same OCR path. Needs provider credentials to verify live (decision 3 above). | OPEN |
| V8 | Vision-model fallback for stylised menus tesseract cannot read; spend bounded by the cost ledger. | OPEN |
| V9 | Arabic / transliterated name matching below the 0.82 bar (R8); needs a labelled sample to tune safely. | OPEN |
| V10 | Run the live-DB suites and a real-tesseract run in the project's Docker stack; none could run in the authoring environment. | OPEN (CI) |

### V6 design (not built)
`competitor_intel_review(tenant_id, global_competitor_id, name_key, source_host, verdict CHECK IN ('CONFIRMED','CORRECTED','REJECTED'), corrected_price, currency, reviewed_by, reviewed_at)`.
`save_site_intel` re-applies verdicts after every re-read (CONFIRMED -> confidence 1.0 and `verified: true`; CORRECTED -> the owner's price; REJECTED -> fact dropped). RLS identical to `competitor_intel`. API: `POST /competitors/{id}/intel/review`.

### Compatibility notes for this roadmap
* No migration is required by V1-V5: facts keep living in `competitor_intel.payload` (JSONB); new payload keys are additive (`extracted_by`, `source_media`, `also_seen_in`, `conflicts_with_price`). The ledger already allows the `PRICES` facet.
* `collect()` gains optional parameters only; every existing call keeps its behaviour. `_safe_get` gains optional `max_bytes` / `accept`.
* New env settings (all optional): `DISCOVERY_OCR_LANGS`, `DISCOVERY_MENU_MEDIA_MAX_FILES`, `DISCOVERY_MENU_MEDIA_MAX_BYTES`, `DISCOVERY_MENU_MEDIA_MAX_PDF_PAGES`, `DISCOVERY_INTEL_DEEP_MAX_PAGES`, `DISCOVERY_INTEL_DEEP_MAX_ITEMS`.
* Dockerfile.ai installs `tesseract-ocr` (+ara, eng); without it pictures are reported as skipped, never an error.
