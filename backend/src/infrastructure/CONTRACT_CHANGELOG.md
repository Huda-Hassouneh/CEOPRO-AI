# KEEL - Infrastructure Contract Changelog

All breaking changes, database constraint adjustments, and API/Event contract modifications between Web-App, Ingestion, and AI/ML teams are strictly tracked here.
## - 2026-07-27
### Added
- Initialized core relational multi-tenancy database schema (`init_schema.sql`).
- Added critical `product_scores` and `campaigns` production tables to database configuration.
- Deployed live asynchronous message broker streaming topics inside Redis (`init_broker.py`).
- Integrated strict `X-Internal-Service-Token` middleware authentication policy (`security.py`).
- Configured automated multi-tenant raw ingestion sample files under `/mocks`.

## - 2026-10-16
### Added (all additive; no existing field, column, or endpoint removed or renamed)
- **DB** — migration `20261016000000_add_competitor_category_and_confidence.sql`: new nullable columns only. `global_competitors`: `category_path`, `address`, `phone`, `rating`, `rating_count`, `place_types`. `tenant_competitors`: `category_similarity`, `confidence_score` (0-100), `confidence_label` (High/Medium/Low), `confidence_reasons`, `confidence_breakdown`, `classification_reason`, `evidence_id` (FK to `evidence_records`, `ON DELETE SET NULL`). Existing rows are valid unchanged (all NULL) until re-scored. RLS policies unchanged; the new columns are covered by the existing per-table policies.
- **API** — `GET /dashboard/competitors`: every existing field and both groups (`strategic`, `relevant`) unchanged, including the exact `summary_line` wording. New per-row fields: `confidence_score`, `confidence_label`, `confidence_reasons`, `confidence_breakdown`, `confidence_summary`, `category`, `category_match_pct`, `address`, `phone`, `rating`, `rating_count`, `distance_km`, `competitor_scope`, `found_via`, `matched_product_count`. New top-level key `possible` (always present, empty unless `separate_weak_leads=true`). New optional query params: `separate_weak_leads`, `min_confidence`, `max_distance_km`, `limit`, `offset` (omitting all of them returns the original shape).
- **API** — new `POST /competitors/reclassify` (tenant-scoped, same auth as `POST /competitors`): re-scores the caller's own competitors.
### Changed (behaviour — consumers should know)
- `GET /dashboard/competitors` ordering: **confidence_score descending** (was alphabetical by name); unscored rows last, alphabetical.
- `tenant_competitors.tier = 'CANDIDATE'` (not tracked) now also means "different business category" (previously only manufacturer / out-of-region). A competitor in a different segment from the tenant (e.g. a donut shop for a burger restaurant) is no longer `is_tracked`, so it disappears from every consumer that already filters on `is_tracked` (dashboard, search, metrics, pricing, MPI, extraction catalog, RAG context/summaries). Manually added competitors and those with >= 60% product overlap are never excluded by category.
- A domain-level find (Places / industry search) is `STRATEGIC` only when its category is in the same segment as the tenant's; related-but-different or unverifiable categories are `RELEVANT` (previously always `STRATEGIC`).
- `global_competitors.competitor_name` for product-search finds is now the seller's hostname (was the product page title). `POST /competitors/reclassify` repairs existing rows.
- Seeded retailer domains (`RETAILER_DOMAINS_BY_VERTICAL`) are only used for tenants operating in the retailer's origin country; operator override: env `RETAILER_INTERNATIONAL_DOMAINS`.
### Spec alignment
- S22: each classification outcome is recorded in `evidence_records` (`source_module = competitor_classification`, `FACT` or `UNKNOWN`), written only when tier/score changes.
- S20: confidence weights are configurable (`COMPETITOR_CONFIDENCE_WEIGHTS`) and every row exposes its per-signal breakdown.
- Data ownership matrix unchanged: competitor data is still written only by the AI Market Scraper Service code path (`discovery.py` / `competitor_classification.py`); the new endpoint calls into that same path.

## - 2026-10-17
### Added (additive)
- **DB** — migration `20261017000000_add_competitor_tracking_decision.sql`: nullable `tenant_competitors.tracking_decision` (`USER_TRACKED` / `USER_UNTRACKED`). Written by the owner's track/untrack action (`discovered_competitors.set_tracked`); NULL for every existing row.
- **API** — `GET /dashboard/competitors` and `GET /competitors/{id}` rows gain `maps_url` and `tracking_decision`. `GET /discovery/competitors`: new `sort=confidence` (competitive confidence, best first; ties by business-is-real `confidence`, then relevance). Each row gains `confidence_score` (0-100, how sure it COMPETES), `confidence_label`, `confidence_reasons`, `category`, `classification_reason`, `tracking_decision`, `maps_url`. The existing `confidence` (0-1, how sure the business is real), `relevance` and all other fields are unchanged. Default sort is unchanged (`relevance`).
### Changed (behaviour)
- `GET /competitors` (flat list): **default order unchanged (alphabetical by name)**; new optional `sort=confidence` orders by `confidence_score` descending (unscored last, then name). Unknown `sort` values are rejected (422).
- Discovery (`market_discovery`) no longer lists a business in a different SEGMENT from the company (e.g. a donut shop for a burger restaurant) unless it has stronger evidence (same products at a published price, or the company's own specialty). Only a positive mismatch excludes; unknown categories are never excluded.
- After every discovery run, competitors are scored (category, competitive confidence, shared evidence record). Re-scoring never starts tracking a competitor that is not tracked, never changes a suggestion's tier, and never overturns an owner's explicit track/untrack choice. It may stop tracking a competitor the SYSTEM tracked if it is in a different category. `auto_track` no longer re-tracks a competitor the owner untracked.
- The Places-nearby discovery path skips permanently closed businesses.

## - 2026-10-18 (competitor data completeness + retry)
### Added (all additive; no existing field, column, or endpoint removed or renamed)
- **DB** — migration `20261018000000_add_competitor_enrichment.sql`: nullable `global_competitors.google_place_id` and `social_profiles` (JSONB); new table `competitor_enrichment` (per tenant + competitor + facet: status, reason_code, reason_detail, attempts, items_found, data_confidence, last/next attempt) with RLS `tenant_id = get_current_tenant()` and a cascade FK to `tenant_competitors`. Migration `20261018010000_add_enrichment_sweep_function.sql`: `list_tenants_with_due_enrichment()` (SECURITY DEFINER, tenant ids only, granted to `ceopro_app`).
- **API** — `GET /dashboard/competitors` rows gain `data_completeness` (`{score, facets: {PROFILE|SOCIAL_LINKS|REVIEWS|PRICES|SOCIAL_CONTENT: {status, reason_code, reason_detail, items_found, confidence, last_attempt_at, can_retry, action, action_source_ids}}}`; `null` if it could not be computed). A PRICES gap caused by unreviewed terms carries `action: "review_source"` and the source ids to pass to the existing `POST /competitors/sources/{source_id}/review`.
- **API** — `GET /competitors/{id}/data-status` (same object plus `queued`); `POST /competitors/{id}/enrich` (optional body `{"facets": [...]}`; synchronous, or `?background=true` -> `202`); `POST /competitors/enrich-failed` ("retry all failed", `202`). Retry is additive. A setup/provider problem is returned as that facet's `reason_code`, not an HTTP error. `422` unsupported facet, `404` unknown competitor, `429` + `Retry-After` for a too-fast retry, `503` when the queue is down. Gated by the same `COMPETITOR_MANAGEMENT` entitlement as the other competitor routes.
- **Event** — Redis stream `market.enrichment.requested` (payload `tenant_id`, `competitor_id` or empty, `facets` csv or empty, `mode` `due|force`), dead-letter `market.enrichment.dead`, group `ceopro-market-enrichment`; new service `market-enrichment-worker` (also an hourly sweep).
### Changed (behaviour — consumers should know)
- Places nearby discovery keeps a business that has no website: registered with `website_url = NULL` under identity key `place:<place_id>`. `website_url` may therefore be `null` on a competitor row.
- After each discovery pass up to `ENRICHMENT_MAX_PER_RUN` competitors are enriched; a profile that gains an address/rating is re-scored, so `confidence_*` can change. Permanent misses (`NO_MATCH`, `NO_SOCIAL_LINKS`) are not retried automatically.
- Google reviews are stored as competitor-level `reviews` rows (`collection_method = PUBLIC_API`, source "Google Places (official API)", up to 5 per listing) only when the operator sets `PLACES_TERMS_APPROVAL_REFERENCE`; new reviews trigger `market.analysis.requested`.
- Data ownership matrix unchanged: competitor data is still written only by the AI Market Scraper Service code path.

## - 2026-10-18 (market price coverage)
### Added (additive)
- **API** — `GET /pricing/market-coverage` (`include_covered`, `limit`, `offset`): `summary` {total_products, with_market_price, without_market_price, coverage_pct, gaps_by_reason} over every product, and `products` listing each product with no competitor price and its `reason_code` (`NO_COMPETITOR_MAPPED | TERMS_UNREVIEWED | ROBOTS_DISALLOWED | NO_DATA_COLLECTED`). A `TERMS_UNREVIEWED` gap carries `action: "review_source"` and the `source_ids` for `POST /competitors/sources/{source_id}/review`. Same `COMPETITOR_MANAGEMENT` entitlement as the competitor routes. Manual prices count as covered.
### Changed
- `supervisor.py` runs the new `enrichment` worker (also selectable via `KEEL_WORKERS`); without this the enrichment queue and hourly sweep would not run on the Render worker service.

## - 2026-10-18 (market reference prices)
### Added (additive)
- **DB** — migration `20261018020000_add_market_price_observations.sql`: `market_price_observations` (tenant-scoped reference prices: provider, seller, listing title/url, price + currency, listing star rating and review count, title `match_score`, `plausible`) and `market_price_lookups` (one row per product: last outcome, sources tried, attempts), both RLS `tenant_id = get_current_tenant()`. Reference prices are deliberately **not** written to `competitor_prices`.
- **API** — `POST /pricing/market-coverage/fill` (`202`, queues a tenant-wide lookup on the enrichment worker); `GET /pricing/market-prices/{product_id}` (reference prices with seller, price, rating, review count, public link; vendor names are not exposed).
- **Event** — enrichment stream job mode `prices`.
### Changed (behaviour)
- `GET /pricing/market-coverage`: a product with a plausible reference price now counts as covered. New per-product `price_basis` (`competitor` | `market_reference`), `reference_prices`, `market_lookup` {outcome, last_attempt_at}; new summary keys `with_competitor_price`, `with_reference_price_only`. Existing keys unchanged.
- New optional `PRICE_LOOKUP_AUTO=true` runs the lookup after each discovery pass (default off: it spends search quota).

## - 2026-10-18 (likes as agreement)
### Added (additive)
- **API** — `GET /dashboard/competitors` rows gain `agreement_weighted_sentiment_score` (-1..1; each comment counts once plus once per like, i.e. per person who agreed) and `people_agreeing` (total likes across the competitor's analyzed comments). `sentiment_score` / `market_sentiment_label` are unchanged. Both are `null` with no analyzed comments.

## - 2026-10-18 (price lookup hardening, verified against live services)
### Changed (behaviour)
- Reference-price lookup: Open Prices uses an exact barcode when the product records one in `products.metadata` (`barcode`, `gtin` or `ean`); otherwise it name-searches Open Food Facts' search service and only queries prices for hits whose brand, name and pack size match. Prices older than `PRICE_LOOKUP_MAX_AGE_DAYS` (365) are ignored and each price keeps its own observed date. Name search alone cannot find every popular product (the price service has no name filter) - a barcode is the reliable key. Pack sizes match with or without a space ("400 g" = "400g").
- Transient provider failures (timeout, connection error, 5xx) are retried once.
### Fixed
- `research/page_reader.py` (assistant research and the new seller-page price lookup): a gzip/deflate-compressed page was reported unreachable because the already-decompressed body was re-wrapped with its `Content-Encoding` header and decompressed twice. Also stops advertising brotli, whose streams failed to decode when the optional package was installed.

## - 2026-10-18 (product barcodes)
### Added (additive)
- **API** — `POST /products` and `PATCH /products/{id}` accept an optional `barcode` (EAN-8, UPC-A, EAN-13 or GTIN-14; spaces/hyphens ignored; length and GS1 check digit validated, `422` otherwise). `PATCH` with `barcode: null` clears it; omitting it leaves it alone. `GET /products/{id}` and the create/update responses return `barcode` (`null` when none). Stored in `products.metadata->>'barcode'` - no schema change; other metadata keys are preserved.
- Why: a barcode is the exact key for the market reference-price lookup (Open Prices), which cannot reliably find a product by name.

## - 2026-10-18 (barcode column on imports)
### Added (additive)
- **Import** — files may include a barcode column (headers such as `barcode`, `EAN`, `UPC`, `GTIN`, `code barre`, `الباركود`; not `SKU`/`product code`). Cells mangled by Excel (`3017620422003.0`, `3.017620422003E+12`, a UPC-A that lost its leading zero) are repaired when the GS1 check digit confirms the repair; an invalid cell is ignored and never blocks the row. The distributed template (`templates/apex_sales_import_v1.*`, version unchanged) gains an optional `barcode` column.
- **Behaviour** — a product that has no barcode gets the file's (fill-only: an existing barcode is never overwritten, and a barcode already owned by another product is not reused). A row whose product name is new but whose barcode belongs to an existing product is recorded against that product instead of creating a duplicate. Duplicate-row detection is unchanged (the barcode is not part of a row's identity).
- **API** — `POST /extraction/upload` promotion summary gains `barcodes_applied` and `products_matched_by_barcode`.

## - 2026-10-18 (barcode prompts)
### Added (additive)
- **API** — `GET /pricing/market-coverage`: each product carries `has_barcode` and, for a price gap with no barcode, `suggestion: "add_barcode"`; summary gains `products_without_barcode` and `gaps_without_barcode`. New query `missing_barcode=true` lists every product without a barcode (price gaps first) as the owner's worklist.
- **API** — `GET /onboarding/status` gains `barcodes` {products, with_barcode, coverage_pct} (omitted if it cannot be computed; the existing keys are unchanged).

## - 2026-10-18 (competitors for products and for the whole business - full detail)
### Added (additive)
- **API** — `GET /dashboard/products/{id}/intelligence`: `product.barcode`; `competitors.price_coverage` (has_market_price, price_basis, reason_code, action, source_ids, has_barcode, market_lookup), `competitors.reference_prices` (seller, price, the listing's own rating and review count, link, counted), `competitors.reference_market` (low/average/high of counted public listings); each product-level and industry-level competitor gains `details` (Google rating and review count, comments collected, people agreeing, sentiment plain and agreement-weighted, social profiles, data completeness). Existing keys unchanged; the new block is omitted-safe (empty values) if it cannot be computed.
- **API** — `GET /competitors/{id}/reviews?sort=helpful|recent&limit&offset`: the real comments collected about one competitor (text, rating, `people_agreeing`, replies grouped under their parent, platform, sentiment) with a summary (comments, replies, people agreeing, per platform, `held_back_for_safety`). Comments from unapproved sources or held by the safety scan are never returned, only counted.
- **API** — `GET /competitor-data/overview`: one bulk read, keyed by competitor id, of the same per-competitor `details` for the list screens.
- **UI** — Competitors screen: per-competitor rating / comments / people agreeing / sentiment / completeness with Retry, "Retry all failed", and a market-price coverage panel (gaps with reasons, "Find missing prices", barcode worklist). Competitor page: data completeness (what is missing, why, Retry) and the real comments. Product page: public-listing prices with the listing's rating and review count, why a price is missing, find prices, barcode entry. English and Arabic.

## - 2026-10-19 (more competitor sources: news, comments, likes)
### Added (additive)
- **DB** — `20261019000000_add_competitor_news_and_comment_facets.sql`: the enrichment ledger accepts two more facets, `NEWS` and `COMMENTS`; `market_news` gains nullable `source_kind` (`own_site` | `web_search` | `gdelt`) and `summary` (the excerpt the source published). `20261019010000_add_comment_retention.sql`: `enforce_comment_retention()` deletes comments from the `youtube_comments` source once older than its `retention_days` (30); `market_scraper/maintenance.py` runs it and reports `comments_deleted`. (The existing retention job only blanks reviewer names; it never deletes review text.)
- **Sources** — NEWS: the competitor's own website feed (RSS/Atom, found from its homepage, robots-aware) and the news mode of the configured web-search provider (Brave, Tavily, SearXNG); only items that name the competitor are kept. Google News RSS is not used (personal-use-only terms). COMMENTS: public YouTube comments with like counts and replies on videos naming the competitor (`YOUTUBE_API_KEY`). REVIEWS: when `APIFY_API_TOKEN` (or the older `APIFY_TOKEN`) is set, a listing's Google reviews are read deeper than the Places API's five, with likes and the owner's replies, without duplicating the five.
- **API** — `GET /discovery/news` articles gain `source_kind` and `summary`. Data-completeness facets gain `NEWS` and `COMMENTS`; new reason codes `NO_FEED`, `NO_NEWS`, `NO_VIDEOS`. `POST /competitors/{id}/enrich` accepts `NEWS` and `COMMENTS` in `facets`.
### Changed (behaviour)
- The routine runs (after discovery, the hourly sweep, "retry all failed") collect profile, social links, reviews and news; video comments (a YouTube search costs 100 quota units) only run on the per-competitor Retry or when requested explicitly.
- Storing YouTube comments, and the deeper Google reviews, needs the operator's recorded approval (`EXTERNAL_COMMENTS_APPROVAL_REFERENCE`; Google reviews keep using `PLACES_TERMS_APPROVAL_REFERENCE`).
- Completeness scores are out of seven facets (was five).


## - 2026-10-18 (pricing never reports "no data")
### Changed (behaviour — consumers should know)
- **API** — `POST /pricing/recommend` no longer returns `status: "UNKNOWN"` for a product without tracked in-region competitor prices. Every product now gets `status: "OK"` and an `action` (`raise` / `lower` / `hold`). New response field `data_basis`: `LOCAL_MARKET` (measured in-region competitor prices; unchanged behaviour) | `MARKET_REFERENCE` (plausible `market_price_observations` for the product, same currency) | `REGIONAL_ESTIMATE` (out-of-region prices converted to the tenant currency and scaled by a regional factor learned from the tenant's own catalog) | `PEER_ESTIMATE` (cost x the market-to-cost multiple of comparable products) | `INTERNAL_ONLY` (own cost/margin only; `market` is `null`). Estimates carry a capped `confidence_score` (<= 0.50 / 0.45 / 0.30 / 0.15) and an explanation prefixed with the basis. Spec S19's "no currency conversion alone" rule is met by the learned regional factor; the original amount/currency of every converted price stays in the explanation (S9). Evidence records gain `market_observation_ids` and `data_basis`.
- Competitor price freshness window: 30 -> 1095 days (`PRICING_MAX_PRICE_AGE_DAYS`); each competitor's latest price is still the only one used. Data older than 90 days is disclosed in the explanation.
- Competitors excluded only for being out of region (`tenant_competitors.classification_reason LIKE 'excluded: competitor country%'`; never manufacturers) are now scraped (`load_scrape_targets`) and used as regional-estimate references. They stay `is_tracked = FALSE` and remain out of every other consumer.
- Discovery: a product with no find in the tenant's region is searched again without the region restriction (`widen_out_of_region`, default on; result rows carry `out_of_region_search`). A mapped product with no price after 7 days (`DISCOVERY_RETRY_UNPRICED_AFTER_DAYS`) is re-searched by `skip_already_discovered` runs.
### Added (all additive; no DB change)
- **API** — `POST /pricing/recommend-all`: a decision for every active product; one failure does not stop the batch.
- Env: `PRICING_DEFAULT_REGIONAL_FACTOR` (default `1.0`, used only when no product has prices in both markets to learn the factor from); `SEARXNG_SECRET` (passed to the SearXNG container from `backend/.env`).
- Frontend: the price recommendation modal states what an estimate is based on (`pricing.modal.estimate.*`, en/ar).

## - 2026-10-19
### Added (additive; no database migration)
- **API** - `POST /competitors/{id}/enrich` accepts `facets: ["PRICES"]` (previously rejected with 422) and an optional `depth` (`"standard"` default, `"deep"` = "load more": more pages, items and menu files). `depth` is also honoured with `background=true`. An invalid `depth` is 422. Omitting both keeps the previous behaviour for every other facet; the default (no `facets`) now includes PRICES, which re-reads the competitor's website.
- **API** - `GET /competitors/{id}/data-status` and `data_completeness` on the competitor lists: the PRICES facet now reports the specific reason from the last website read (`NO_PRICES_PUBLISHED`, `JS_RENDERED`, `OCR_NOT_AVAILABLE`, `NOT_OWN_SITE`, plus the existing `ROBOTS_DISALLOWED` / `SITE_UNREACHABLE`) when no price has been matched to a product yet, and `can_retry: true` on it. New reason codes are additive strings (the column is `VARCHAR(40)`, no CHECK).
- **Data** - `competitor_intel.payload` (JSONB) for `kind = 'product'` facts read from menu PDFs / pictures carries `extracted_by` (`pdf_text` | `ocr`) and `source_media: true`; a price confirmed by two places carries `also_seen_in` (list of URLs); a price that disagrees with the page text carries `conflicts_with_price`. `source_url` is the menu file. `confidence`: PDF text 0.7, OCR 0.5 (0.4 without a currency symbol); +0.05 when corroborated.
- **Event** - stream `market.enrichment.requested` messages may carry `depth: "deep"`; absent means standard (older producers/consumers unaffected).
- **Infra** - `Dockerfile.ai` installs `tesseract-ocr` (+ `ara`, `eng` data); `pytesseract` added to `src/ai/requirements.txt`. New optional env: `DISCOVERY_OCR_LANGS`, `DISCOVERY_MENU_MEDIA_MAX_FILES`, `DISCOVERY_MENU_MEDIA_MAX_BYTES`, `DISCOVERY_MENU_MEDIA_MAX_PDF_PAGES`, `DISCOVERY_INTEL_DEEP_MAX_PAGES`, `DISCOVERY_INTEL_DEEP_MAX_ITEMS`, `DISCOVERY_INTEL_DEEP_MAX_MEDIA`.
### Changed (behaviour)
- `competitor_intel.save_site_intel`: a re-read that found menu files but could not read any (OCR missing, fetch failed) no longer deletes the menu-derived facts from an earlier read ("a retry only adds").
- `refresh_competitor` returns an extra `media` key (`found`, `read`, `skipped_no_ocr`, `ocr_available`).
- `enrich._safe_get` takes optional `max_bytes` and `accept` (defaults unchanged).

## - 2026-10-19 (second entry: V6-V9)
### Added (additive)
- **DB** - migration `20261023000000_add_competitor_intel_review.sql`: new table `competitor_intel_review` (owner decisions on website/menu/social prices, keyed by item name + price as read; RLS `get_current_tenant()`, FK to `tenant_competitors` ON DELETE CASCADE). No existing table or column changed.
- **API** - `POST /discovery/competitors/{competitor_id}/intel/review` (owner/admin; plan feature COMPETITOR_MANAGEMENT): body `{intel_id, verdict: CONFIRMED|CORRECTED|REJECTED|CLEARED, corrected_price?, currency?, note?}`; 200 returns the decision and the refreshed intel; 403 other roles, 404 unknown fact, 422 invalid combination. Prices are re-matched to products afterwards.
- **API** - every fact in `GET /discovery/competitors/{id}` / refresh `intel` (products, promotions, messages, social) now carries `intel_id`; reviewed products carry `verified`, `verdict`, and (corrected) `read_price`.
- **API** - `POST /competitors/{id}/enrich` accepts `facets:["SOCIAL_CONTENT"]` (previously 422). `depth:"deep"` also reads more posts. SOCIAL_CONTENT reasons: `NO_SOCIAL_LINKS`, `COLLECTOR_NOT_ENABLED`, `NO_CREDENTIALS`, `PLATFORM_APPROVAL_MISSING`, `NO_POSTS`, `NO_PRICES_PUBLISHED`, plus provider/budget codes. SOCIAL_CONTENT is a paid provider call, so it is NOT part of a plain retry (no `facets`): only an explicit `facets:["SOCIAL_CONTENT"]` runs it, and even then it is refused (never sent) until the operator has set the token, the approval reference and a cost row.
- **Data** - `competitor_intel.payload` for social-post facts: `channel` (`instagram` | `facebook`), `extracted_by` (`caption` | `ocr` | `vision`), `post_taken_at`; `source_url` is the post. Website facts have no `channel` (treated as `website`). A website re-read (`save_site_intel`) only replaces `channel`-less / `website` facts; `save_channel_facts` only replaces its own channel.
- **Provider billing** - host `generativelanguage.googleapis.com` is classified as paid provider `gemini_vision` / operation `read_image` (refused until priced).
- **Infra / env (all optional)** - `DISCOVERY_VISION_OCR` (off|fallback|always, default off), `DISCOVERY_VISION_MAX_FILES`, `DISCOVERY_VISION_MODEL`, `GEMINI_API_KEYS` (existing), `SOCIAL_CONTENT_APPROVAL_REFERENCE`, `SOCIAL_CONTENT_POSTS(_DEEP)`, `SOCIAL_CONTENT_IMAGES(_DEEP)`, `APIFY_INSTAGRAM_POSTS_ACTOR`, `APIFY_FACEBOOK_POSTS_ACTOR`.
### Changed (behaviour)
- Places candidate matching (`competitor_enrichment._find_place`, `spiders/google_places.py`) uses `name_matching.name_similarity`: Arabic / Latin / transliterated spellings of one business now clear the 0.82 bar. It is never lower than the previous plain ratio, so no match that passed before is lost; matches that previously failed across scripts may now pass.
- Automatic price matching (`offerings.competitor_items`) ignores social-post facts until the owner has confirmed them.
### Infra (same day, after review)
- `tesseract-ocr` (+ `ara`, `eng`) is now installed in `Dockerfile.ai`, `src/infrastructure/Dockerfile.market-workers` and `src/infrastructure/Dockerfile.market-scraper`; `src/market_scraper/requirements.txt` gains `Pillow`, `pdfplumber`, `pytesseract` (the worker images read menus too).
- `docker-compose.yml` (API and enrichment worker) and `render.yaml` (API and worker) pass `SOCIAL_CONTENT_APPROVAL_REFERENCE`, `DISCOVERY_VISION_OCR` (default `off`) and `GEMINI_API_KEYS`.
- `intel_review.load_reviews` reads inside a savepoint and treats a missing `competitor_intel_review` table as "no decisions", so a code deploy that precedes the migration cannot break site reads.
### OCR behaviour (same day, after a real-tesseract check)
- Pictures are read with two tesseract passes when Arabic data is installed (`ara+eng`, then `eng`) and merged by amount; Arabic output returned in visual order is restored, direction marks and a few stray Arabic letters beside Latin text are removed, and an Arabic currency word misread by one letter is restored. `python-bidi` is added to `src/market_scraper/requirements.txt` (already in the AI requirements). New optional env: `DISCOVERY_MENU_MEDIA_BUDGET_SECONDS` (default 90 s of menu reading per site).


## - 2026-10-19 (price comparison tiers)
### Added (all additive; no existing field, column, or endpoint removed or renamed)
- **DB** - migration `20261024000000_add_product_price_comparisons.sql` (rollback in `database/rollback/`): new table `product_price_comparisons` (one row per tenant + product + competitor + tier: `tier` EXACT | EQUIVALENT | SIMILAR | ADDED_VALUE, `direction`, `match_score`, `scale_factor`, the competitor's item name and price, `comparable_price`, `price_delta_pct`, `reasons`, `premium`, `method`, `source_url`, `observed_at`). RLS `tenant_id = get_current_tenant()`, FKs to `products` and `tenant_competitors` with `ON DELETE CASCADE`. **`competitor_prices` is unchanged and still holds exact prices only**; similar, scaled and added-value prices are deliberately not written there.
- **API** - `GET /pricing/comparisons?product_ids=a,b,c` (<= 100 ids): per product `{covered, headline {tier, count, median_comparable, position_pct}, counts per tier}`. `GET /pricing/comparisons/{product_id}`: the full ladder (`tiers.<TIER> {count, items[], low, median, high, your_position_pct}`; each item has the competitor's own price, `scale_factor`, `comparable_price`, `price_delta_pct`, `direction`, `reasons`, `premium` for ADDED_VALUE, `source_url`, `observed_at`). `POST /pricing/comparisons/refresh`: recomputes from stored competitor items (no crawl, no credits); gated by `COMPETITOR_MANAGEMENT` like the other competitor writes. Reads are tenant-scoped like `/pricing/recommend`; another tenant's product is a `404` / absent from the summary.
- **API** - `POST /pricing/recommend` and `/recommend-all`: `data_basis` gains the value `COMPARABLE_ESTIMATE` (see below). The evidence payload gains `price_comparison_ids`. All existing keys are unchanged.
### Changed (behaviour - consumers should know)
- A product with no tracked in-region exact competitor price now tries its EQUIVALENT competitor items (the same item in another quantity, scaled to the product's) and then its SIMILAR items **before** the market-reference, regional and peer estimates. Confidence is capped at 0.55 (equivalent) / 0.40 (similar) and the explanation is labelled `[COMPARABLE_ESTIMATE]`. ADDED_VALUE rows are never averaged into a price. Products that already have an exact local price are unaffected.
- Discovery (`market_discovery/pipeline.py::_match_prices`) classifies every priced competitor item against the company's products after the exact matcher runs (`market_scraper/price_comparison/`). Failures there are logged and never fail the run; a deployment without the table skips it.
### Spec alignment
- S19: each comparison keeps the competitor's own price, collection date and source link; prices of different currencies are never compared; an estimate is labelled as one.
- Data ownership matrix unchanged: the table is written only by the AI Market Scraper Service code path (`price_comparison/engine.py`), read by the `ai` API.
### Follow-up (same day, accuracy)
- `product_price_comparisons.reasons` may contain `specificity_unclear` ({side, words}) and `ai_judged` ({verdict, side, words}); `method` may be `AI_ASSISTED`. No schema change.
- Compound spellings ("cheeseburger" / "cheese burger") now match. A name that is another item's name plus unplaceable extra words is shown as SIMILAR, flagged `specificity_unclear`, and excluded from `COMPARABLE_ESTIMATE` until judged. When an AI model is configured and `DISCOVERY_AI_HINTS` allows it, discovery and `POST /pricing/comparisons/refresh` ask it (at most `PRICE_COMPARISON_AI_MAX_PAIRS`, default 60, per run) whether the extra words are an addition or a variant; it never handles prices.
### Follow-up (owner override)
- **DB** - migration `20261026000000_add_price_comparison_overrides.sql` (rollback in `database/rollback/`): table `product_price_comparison_overrides` (tenant, product, competitor, normalized item name, verdict ADDITION | VARIANT | NOT_COMPARABLE, decided_by/at); RLS `get_current_tenant()`, cascade FKs. Code deployed before it simply has no decisions.
- **API** - `PUT /pricing/comparisons/{product_id}/override` `{competitor_id, item_name, verdict}` (`null` clears): owner/admin only, `COMPETITOR_MANAGEMENT`; `403` otherwise, `404` for an unknown product/competitor, `422` for an unknown verdict. Returns the product's ladder. Overridden rows have `method: "OWNER"` and reason `owner_decision`; decisions persist across recomputes.
### Follow-up (hardening)
- `POST /pricing/comparisons/refresh` now answers with rules only and adds `unsettled` and `ai_pending`; the AI check of unclear pairs runs afterwards in the background. The override endpoint no longer calls the model. Earlier AI verdicts and owner decisions are reused on every recompute.
- Behaviour fix: `POST /discovery/competitors/{id}/intel/review` with `REJECTED` now also marks the `competitor_prices` rows recorded from that item `is_available = FALSE` (matched by the mapping's item-name sku and the price as read), so a rejected price stops counting as an exact competitor price in pricing, coverage and the ladder. Other verdicts are unchanged.

## - 2026-10-20 (price comparison accuracy)
- No schema or API change. Classifier behaviour only: a number glued to a unit or code (`110mm`, `20000mAh`, `E6013`) is never treated as a spelling variant of another, so different pipe sizes, capacities and grades are SIMILAR, not EXACT; a half-day or part-month quantity is SIMILAR (never EQUIVALENT to a whole day); `platter` is ignored like other format words; names that differ only by a colour or fabric on each side (EN/FR/AR) are related as SIMILAR. Existing rows change on the next refresh or discovery run.
- New: `scripts/price_comparison_eval.py` (score / export) and a regression gate (`market_scraper/tests/test_price_comparison_accuracy.py`).
- **API (additive)** - ladder objects (`GET /pricing/comparisons/{id}`, the override response) gain `premium_band` `{band_pct, source: default|observed, samples}` and `added_value_guidance` (`null`, or `{kind: "range_not_a_price", base_price, range_low, range_high, band_pct, band_source, band_samples, your_price, position, your_premium_pct}`); an ADDED_VALUE item's `premium` is re-read against its category's band and may carry `band_source` and `band_samples`. `POST /pricing/recommend` gains `added_value_guidance` (same shape or `null`) and appends a sentence to `explanation`; the price, action and confidence are unchanged.
- **API (new)** - `GET /reports/price-comparison?limit=` (default 50, max 200): `{products: [{name, ...ladder}], count}`, read-only, tenant-scoped.
- Assistant: a `price_ladder` fact section is offered for pricing, competitor and advice questions.
- Premium bands are computed per category at read time from the tenant's own added-value premiums (75th percentile, at least 5 pairs, clamped to 20-150 %); otherwise `PRICE_COMPARISON_PREMIUM_BAND_PCT`. No schema change.
- **DB** - migration `20261027000000_add_price_premium_band_overrides.sql` (rollback in `database/rollback/`): table `price_premium_band_overrides` (tenant, `category_key`, `band_pct` 5-300, set_by/at), RLS `get_current_tenant()`, FK to `companies` with cascade. Code deployed before it simply has no owner-set bands.
- **API (new)** - `GET /pricing/premium-bands` -> `{default_band_pct, categories: [{category, band, observed}]}` (`band.source`: owner | observed | default); `PUT /pricing/premium-bands` `{category, band_pct}` (owner/admin only, `403` otherwise; `band_pct` 5-300 else `422`; `null` clears). Ladders gain `category`, and `premium_band.source` / `added_value_guidance.band_source` may now be `owner`.

- Limits: `PUT /pricing/premium-bands` allows at most 200 categories per company (`409` beyond that; changing an existing one is always allowed). `GET /reports/price-comparison` looks at a company's first 500 products. The assistant's `price_ladder` section lists at most 12 products.
- `PRICE_COMPARISON_PREMIUM_BAND_PCT` and `PRICE_COMPARISON_AI_MAX_PAIRS` are now listed in `.env.example` (both optional).

## - 2026-10-20 (competitor comments: reasons, quality, themes, actions, refresh)
Design and as-built notes: `COMPETITOR_COMMENTS_AND_RETRY_PLAN.md`. All additive except the two behaviour changes below.
- **DB** - `20261025000000_add_review_source_url.sql`: nullable `reviews.source_url` (http/https only). `20261026000000_add_comment_action_status.sql`: nullable `reviews.action_status` (`noted` | `acted_on`), `action_by`, `action_at`. `20261026010000_add_comments_refresh_function.sql`: `list_tenants_with_due_comments_refresh(max_age_days)` (SECURITY DEFINER, returns tenant ids only). `20261026020000_add_competitor_review_index.sql`: partial index `idx_reviews_competitor (tenant_id, competitor_id, review_date DESC) WHERE subject_type = 'COMPETITOR'` (competitor reads had no supporting index; checked with EXPLAIN). Rollbacks in `database/rollback/`; the action-status one loses owners' marks, the index one loses nothing.
- **API** - every data-completeness facet (`GET /competitors/{id}/data-status`, `GET /competitor-data/overview`) and every `POST /competitors/{id}/enrich` result gains `next_step` (`none` | `retry` | `wait` | `owner` | `admin`: who has to act); the completeness object gains `needs_setup` (facets waiting on service setup).
- **API** - `GET /competitors/{id}/reviews` gains query params `sentiment`, `platform`, `theme` (service, waiting, price, quality, cleanliness, staff, delivery, availability), `action` (open | noted | acted_on); `summary` gains `sentiment` counts, `themes`, `last_collected_at`, `matching`; each comment gains `signal` (`opportunity` | `threat`, from sentiment and at least 3 people agreeing), `url`, `action_status`, `action_at`.
- **API (new)** - `PUT /competitors/{id}/reviews/{review_id}/action` `{status: noted | acted_on | null}` -> `{id, action_status, action_at}`; 404 for a comment that is not this competitor's or is held back by the safety check. Any signed-in member of the company may mark a comment (no role gate).
- **Alerts** - new kind `competitor_comments_negative` (>= 5 analysed comments in the last 14 days, >= 60% negative; one per competitor per week), in the `market` notification group and the email digest.
- **Queue** - new enrichment mode `comments` (tenant-wide weekly refresh). The worker runs a daily step that queues it for tenants with stale comments; it is skipped when `YOUTUBE_API_KEY` / `EXTERNAL_COMMENTS_APPROVAL_REFERENCE` are unset, and spends at most `YOUTUBE_DAILY_SEARCH_BUDGET` searches a day.
### Changed (behaviour)
- The REVIEWS facet now counts Google reviews only (`source_platform = 'Google Places'`); the COMMENTS facet counts every other platform's visible (allowed, safe) comments and reports `SUCCEEDED` whenever such rows exist, whatever the attempt log says. Before, comments were counted as Google reviews and never made COMMENTS succeed.
- Comments are collected with filters (`COMMENT_MIN_LETTERS`, `COMMENT_MIN_WORDS`, `COMMENT_OFF_CHANNEL_MIN_CHARS`): noise, duplicates and unrelated comments on other people's videos are dropped before they are stored.
- Supersedes the 2026-10-19 note that video comments only run on a manual Retry: they are now also refreshed weekly by the worker (still not part of the hourly routine sweep or "retry all failed").

