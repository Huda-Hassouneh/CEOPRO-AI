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
- **Sources** — NEWS: the competitor's own website feed (RSS/Atom, found from its homepage, robots-aware) and the news mode of the configured web-search provider (Brave, Tavily, SearXNG); only items that name the competitor are kept. Google News RSS is not used (personal-use-only terms). COMMENTS: public YouTube comments with like counts and replies on videos naming the competitor (`YOUTUBE_API_KEY`). REVIEWS: when `APIFY_TOKEN` is set, a listing's Google reviews are read deeper than the Places API's five, with likes and the owner's replies, without duplicating the five.
- **API** — `GET /discovery/news` articles gain `source_kind` and `summary`. Data-completeness facets gain `NEWS` and `COMMENTS`; new reason codes `NO_FEED`, `NO_NEWS`, `NO_VIDEOS`. `POST /competitors/{id}/enrich` accepts `NEWS` and `COMMENTS` in `facets`.
### Changed (behaviour)
- The routine runs (after discovery, the hourly sweep, "retry all failed") collect profile, social links, reviews and news; video comments (a YouTube search costs 100 quota units) only run on the per-competitor Retry or when requested explicitly.
- Storing YouTube comments, and the deeper Google reviews, needs the operator's recorded approval (`EXTERNAL_COMMENTS_APPROVAL_REFERENCE`; Google reviews keep using `PLACES_TERMS_APPROVAL_REFERENCE`).
- Completeness scores are out of seven facets (was five).

