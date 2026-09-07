# CEOPRO AI — Web Crawling / Data Collection Layer

This service implements the market-collection requirements in the system architecture, technical
specification, and `MASTER_SPEC_v4.md` §13. It is the producer for canonical PostgreSQL
`competitor_prices`; downstream price intelligence remains a read-only consumer.

## Architecture

```text
Tenant competitor mapping
        ↓
Collection Policy Engine (API → RSS → structured data → controlled web)
        ↓ only ALLOWED sources
Redis stream: market.scrape.requested
        ↓
Tenant-scoped worker allocation
        ↓
Allowlisted Scrapy/Playwright collector (JSON-LD or reviewed CSS selectors)
        ↓
0.82 product mapping gate + normalization + external-content safety scan
        ↓
Validation + in-run deduplication
        ↓
competitor_prices + market_observations + events + ingestion audit trail
```

The repository's approved development target is `https://books.toscrape.com/`. The
`books_to_scrape` spider supports two modes:

1. **Production-shaped mapped mode** — visits only active product URLs allocated from
   `competitor_product_mappings`, carries tenant/source/job lineage, and persists observations.
2. **Demo catalogue mode** — follows catalogue pagination and exports JSONL without touching the
   database. This exists for development and smoke testing, not competitor production collection.

A real competitor gets its own source-specific spider. Selectors are not shared across unrelated
sites; a giant conditional mega-spider would be neither reliable nor maintainable. Four
API/paid-provider collectors exist alongside the general-purpose `standards`/`MarketSourceSpider`
collector (which, being schema.org/JSON-LD-based, also covers most conventional retailer sites —
Ikea included — without a bespoke spider):

- **`google_places`** (`spiders/google_places.py`) — official Google Places API (Find Place →
  Details), reviews only. Places has no price to report, so every record it yields has
  `price_amount = currency = None`; `market_repository.save_market_record()` skips the
  `competitor_prices` INSERT and price-derived `market_events` for those records but still writes
  `market_observations` and the reviews, through the same Tier-2 staging/0.82-gate/safety-scan
  pipeline as any priced record.
- **`amazon_paapi`** (`spiders/amazon_paapi.py`) — official Amazon Product Advertising API v5,
  exact-ASIN price/availability. AWS Signature Version 4 request signing is implemented with
  stdlib `hmac`/`hashlib` only, no extra dependency.
- **`digikey_api`** (`spiders/digikey_api.py`) — official Digi-Key Product Information API v4,
  exact-part-number price/availability. OAuth2 client-credentials token exchange, real endpoint/
  header names confirmed from Digi-Key's own published docs. **Flagged, not silently hidden**: the
  exact JSON response *field names* (`UnitPrice`, `QuantityAvailable`, etc.) are this module's
  best-effort reading of public documentation, not confirmed against a real authenticated call — no
  credentials are configured in this environment. `_field()`'s multi-candidate-key lookup degrades
  safely if a guess is wrong; `collector_config["field_overrides"]` corrects it without a code
  change. Needs a real credentialed smoke test before being trusted with real spend decisions.
- **`mouser_api`** (`spiders/mouser_api.py`) — official Mouser Search API v1, exact-part-number
  price/availability. Single API-key auth (query string, no OAuth) — real endpoint/request-shape
  confirmed from Mouser's own docs. Same flagged field-name caveat as `digikey_api` above; price is
  parsed via `parsing.py::parse_price()` since Mouser documents it as a currency-symbol string
  (e.g. `"$0.4700"`), not a bare number.
- **`social_data_provider`** (`spiders/social_data_provider.py`) — Instagram/Facebook/TikTok have no
  public API for competitor data and their ToS prohibits direct automated collection, so this repo
  never scrapes them itself (`social_cross_reference.py` is the free, ToS-compliant alternative for
  finding *mentions* of a competitor via Google's own index). This collector instead wraps a paid
  third-party provider's REST API, modeled on Apify's Actor API
  (`run-sync-get-dataset-items`) — one maintained actor per platform. It only ever talks to the
  provider's own API host, never to facebook.com/instagram.com/tiktok.com directly. Two-stage
  collection: one call per competitor profile returns posts with their own like/share/comment-count
  aggregates, then (`collector_config["fetch_comments"]`, default on) one further call per post
  fetches the actual comment list — real text, author, and per-comment like/reply counts, landing in
  `reviews.like_count`/`reply_count` and `market_observations.like_count`/`share_count`
  (`20260906010000_add_engagement_metrics_columns.sql`). Comments are a second, separately-billed
  provider call on top of the posts call — disable `fetch_comments` for the cheaper posts-only mode.
- **`scrape_creators`** (`spiders/scrape_creators.py`) — **the primary, active social provider for
  this deployment** (see "Vendor policy" below). [ScrapeCreators](https://docs.scrapecreators.com)
  is a plain REST API (`x-api-key` header, cursor-based pagination via `cursor`/`has_next_page`),
  not an actor-run platform like Apify. Confirmed live against a real Facebook comments payload
  (2026-09-06): billing is **per call**, not per row returned — one request that returned 10
  comments charged exactly 1 credit — which makes deep comment-thread mining (the actual product
  goal: hidden negative sentiment, complaint themes) far cheaper than a per-row-billed provider once
  a thread runs long. Each target's `competitor_product_url` is treated as a specific post/video URL
  to monitor in depth, not a profile to browse. Instagram/TikTok endpoint paths exist in
  ScrapeCreators' own docs but their exact response field names aren't independently confirmed the
  way Facebook's is — `collector_config["endpoints"]`/`["field_overrides"]` correct that
  per-platform without a code change once checked.

  **Full-thread capture is the default** — product requirement: a truncated thread can hide exactly
  the negative-sentiment comments that matter most. `collector_config["max_comment_pages"]` and
  `["max_credits_per_post"]` both default to `None` (no limit) — pagination for a post runs until
  the provider itself reports `has_next_page: false`, however long the thread actually is. The only
  default ceiling is `["max_credits_per_run"]` (`5000` credits across one whole crawl, roughly $9-10
  at the confirmed Facebook rate) — a circuit breaker against a genuine anomaly (a bug causing a
  runaway request loop, or an entire batch of tracked posts going viral in the same run
  simultaneously), never a data-completeness limit; every response's own real `credits_charged` is
  what's tracked against it, never an estimate. Every real thread should fit comfortably under that
  default in normal operation — set any of the three explicitly (`max_credits_per_run` included, to
  `None`) to change or remove it entirely.

All four require credentials, supplied per-source via `data_sources.connection_credentials_vault`
(a JSON object — `{"api_key": ...}` for Places and for ScrapeCreators, `{"access_key",
"secret_key", "partner_tag"}` for PA-API, `{"api_token": ...}` for the Apify-shaped social
provider) and passed through by `cli.py` as `credentials_json`. That column is a plain `TEXT`
field with no secrets-manager integration behind it yet — see `PENDING_ACTIONS.md` #42.

## Vendor policy for social collection

`scrape_creators` is the primary, active social-data vendor for this deployment — the one
provisioned with real `connection_credentials_vault.api_key` and an `ALLOWED` policy status.
`social_data_provider` (Apify-shaped) stays registered in `collectors.py`/`policy_cli.py` and fully
tested, but is kept **inactive**: no credentials configured, so `PaidProviderNotConfiguredError`
fires immediately if anything ever tries to run it (same as before any credentials exist for it).
This is intentional, not an oversight — it's a cold, ready-to-activate fallback, not a second live
vendor. Switching to it later (a ScrapeCreators outage, a pricing change, wanting Apify's larger
actor-redundancy ecosystem once budget allows) means populating its credentials and pointing
`data_sources.collector_key` at `social_data_provider` for that source — a config/credentials
change, never a code change, because both collectors already share the same constructor contract
and yield the same item shape.

Setting this up for a real tenant:

```bash
# Primary: ScrapeCreators, active
python -m src.market_scraper.policy_cli \
  --tenant-id TENANT_UUID --source-id SOURCE_UUID \
  --source-url https://api.scrapecreators.com --official-api-url https://api.scrapecreators.com \
  --terms-permit yes --technical-controls-permit yes \
  --collector scrape_creators \
  --approval-reference VENDOR-CONTRACT-REF --approved-by REVIEWER_USER_UUID --retention-days 30
# then set that source's connection_credentials_vault to {"api_key": "<real ScrapeCreators key>"}
```

Apify's `social_data_provider` source row, if created at all ahead of time, is left with
`connection_credentials_vault` empty/unset and never approved — it exists in the vault as
configuration, not as a running collector.

## Industry-agnostic discovery orchestration

`tenant_discovery.py::discover_competitors_for_tenant(conn, tenant_id, actor_user_id)` is the
out-of-the-box entry point for "any company, any industry" competitor discovery — nothing about it
is specific to electronics or any single vertical:

1. Loads the tenant's own active product catalog (`products.product_name`).
2. `sector_detection.py::detect_vertical()` reads that catalog and infers a business vertical from
   keyword frequency (electronics/food_beverage/apparel_fashion/home_furniture, or the honest
   `general_retail` fallback when nothing matches confidently) — used only to decide whether the free
   `RETAILER_DOMAINS_BY_VERTICAL` path (below) also applies; it never gates whether discovery runs.
3. `web_product_discovery.py::discover_product_candidates()` — one real Google Custom Search JSON
   API call per product, built from `sector_detection.py::build_retail_search_query()`. This is the
   actual industry-agnostic path: it runs identically for a coffee machine, a sofa, or a resistor.
   Same free-tier setup as `social_cross_reference.py` (100 queries/day): export
   `GOOGLE_CUSTOM_SEARCH_API_KEY` / `GOOGLE_CUSTOM_SEARCH_CX`. Missing credentials, an API error, or
   genuinely no results all return `[]` — never a fabricated candidate.
4. `direct_search.py::search_product_across_retailers()` layers in for free, zero-API-cost, but only
   contributes candidates for a vertical that already has a hand-seeded `RETAILER_DOMAINS_BY_VERTICAL`
   entry (today: `electronics_hobbyist` only, seeded and live-verified during this codebase's own
   validation run — see `direct_search.py`'s docstring for the full verification record). An
   optimization on top of step 3, never a substitute: a tenant in any other vertical still gets full
   coverage from the Custom Search path alone.
5. Every candidate from either path goes through the same `discovery.py::evaluate_candidate()` /
   `register_tenant_scoped_competitor()` used everywhere else in this module — unchanged, already
   fully generic.

Nothing here auto-approves collection. `register_tenant_scoped_competitor()` only ever sets
`approval_reference`/`approved_by` when real, quotable terms evidence is supplied, and a fully
automated discovery run never has any — `policy.py::evaluate_source()`'s own decision table
(`terms_permit_collection is None` is checked before every `ALLOWED` branch) guarantees every
auto-discovered candidate lands as `BLOCKED` or `RESTRICTED`, never `ALLOWED`, regardless of whether
its robots.txt fetch even succeeds. Discovery finds and records candidates; a human still has to
review and approve each one (the existing `cli.py` gate) before any collection actually runs.

## Where competitor URLs and product matching come from

`data_sources.source_url` is the reviewed base/API/feed URL and stores collection policy,
configuration, approval, privacy, rate-limit, and retention metadata. It is not the tenant's whole
competitor registry. `global_competitors.website_url` describes the competitor, while each exact
page allocated to a tenant product comes from
`competitor_product_mappings.competitor_product_url`; that mapping references the approved
`source_id`.

Every extracted product is checked in `spiders/market_source.py`: exact external SKU wins with score
`1.0`; otherwise the extracted name must reach fuzzy similarity `0.82`. `pipelines.py` independently
enforces the recorded method and score before persistence.

## Review-widget fallback (Trustpilot/Bazaarvoice/Yotpo-style)

Live validation this session (real SparkFun/ImpactBattery pages) found reviews aren't always in a
page's JSON-LD - some retailers publish them a different standard way, and some hide them behind a
client-rendered widget with no structured markup at all. `spiders/market_source.py` tries three
layers, in order, stopping at the first that finds anything:

1. **JSON-LD** (`parse_structured`'s original path) - `<script type="application/ld+json">`.
2. **Microdata** (`_extract_microdata_products`, via `extruct`) - the same schema.org vocabulary,
   published as `itemscope`/`itemprop` HTML attributes instead of JSON-LD - a real, documented
   alternative serialization some review-widget SEO integrations (e.g. Bazaarvoice's BVSEO fallback
   markup) use specifically so search engines can index review content a browser only renders via JS.
   Only tried when JSON-LD found nothing, so a normal JSON-LD page pays no extra parse cost.
3. **Widget CSS selectors** (`_widget_reviews`) - last resort, for a widget that renders plain HTML
   with no schema.org markup at all. Requires two things: `render_javascript=True` on the source (so
   `response` is the widget's own post-JS-render DOM, not the pre-render HTML a plain fetch would
   see - already a supported flag via `scrapy-playwright`), and real, reviewed
   `widget_review_container`/`widget_review_text`/`widget_reviewer_name`/`widget_review_rating`/
   `widget_review_date` CSS selectors in that source's `collector_config["selectors"]`. Never a
   guessed vendor-wide selector - same "source-reviewed, not invented" discipline as every other
   selector in this codebase; `widget_review_rating` is read as a bare number, not rescaled the way
   a JSON-LD `aggregateRating` is, since a CSS-extracted value has no `bestRating`/`worstRating` to
   read.

`scripts/live_widget_diagnostic.py <product_url>` renders a real page (headless Chromium via
`playwright`), runs layers 1-2 for real, and - only if both come back empty - scans the rendered DOM
for known review-widget vendor signatures and prints the real surrounding HTML, so the actual
selectors layer 3 needs can be read off real markup rather than guessed. Run it locally (this
sandbox's own network egress can't reach third-party sites); its output is what tells you which
selectors to configure for a given source, not something this codebase invents on its own.

## Real-competitor classification

Discovery (`discovery.py::register_tenant_scoped_competitor`) records every seller found for a
matched product — useful as an audit trail — but not every seller found that way is actually a
competitor. `src/ai/pricing/competitor_classification.py::classify_competitor()` runs immediately
after registration (and can be re-run any time a tenant's catalog/mappings grow) and gates
`tenant_competitors.is_tracked` — the flag `data_access.py::load_scrape_targets()` requires — on
three checks:

1. **Not a manufacturer/wholesaler.** `discovery.py::looks_like_manufacturer_or_wholesale()`
   (domain-matches-brand or a wholesale/distributor/OEM signal word) is persisted as
   `global_competitors.is_manufacturer`; a manufacturer's own store is excluded regardless of
   product overlap.
2. **In the tenant's operating region.** `global_competitors.country_code` is compared against
   `companies.country_code`/`operating_countries`; an unknown competitor country is not excluded
   (no evidence either way), but a known out-of-region one is.
3. **Product overlap meets a configurable threshold.** `product_match_rate` = (this tenant's active
   products this competitor also has an active mapping to) / (this tenant's total active products).
   Only `>= threshold` (default `0.5`, i.e. 50%, passed as a parameter — not hardcoded) confirms a
   real competitor.

`tenant_competitors.product_match_rate`/`is_confirmed_competitor`/`classified_at` record the result
of the most recent classification.

## Collection policy

Every source starts `RESTRICTED`. `policy.py` evaluates and records one of:

- `ALLOWED` — reviewed and usable by the selected method;
- `RESTRICTED` — requires human/compliance or technical review;
- `BLOCKED` — terms, controls, or URL safety prohibit collection.

Method selection is deliberately ordered:

1. official public API;
2. public RSS/feed;
3. public structured data (for example JSON-LD);
4. controlled public web scraping.

Scraping is therefore the fallback, not the default. Unknown terms never magically become
permission. Local/private/credential-bearing URLs are blocked. Scrapy also honors `robots.txt`,
uses configurable rate limits, AutoThrottle, timeouts, bounded retries, no cookies, and no access-
control bypass.

Policy decisions, method, justification, restrictions, review timestamp, and rate limit are stored
on `data_sources`; policy changes are written to `audit_logs`.

## Tier-2 staging and quarantine

Every mapped candidate is first committed to `market_observation_staging` as `PENDING`. Validation
moves it to `REJECTED`, the external-content safety gate moves unsafe text to `QUARANTINED`, and
only safe validated candidates become `PROMOTED`. If product identity/page text is quarantined, the
candidate cannot create `competitor_prices`, events, alerts, reviews, or canonical observations. An
unsafe review on an otherwise safe verified product is quarantined independently: it cannot reach
sentiment/LLM consumers, while the separately verified numeric product price may still be promoted.

The market-specific staging table deliberately complements rather than overloads
`import_staging_rows`: market records need mapping IDs, hashes, safety flags, and market-specific
terminal states. See `MARKET_DATA_PRIVACY_AND_RETENTION.md`.

## Canonical persistence

Mapped observations append to `competitor_prices` with:

- exact `tenant_id` and `mapping_id` lineage;
- captured numeric price and ISO currency;
- availability;
- `ALLOWED` source status and exact/estimated classification;
- UTC observation timestamp.

The service never guesses a tenant, mapping, product, or price. Every mapped observation must match
by exact external SKU or meet the specification's 0.82 fuzzy-name threshold. A failed/missing target
makes the job fail instead of silently reporting success. `ingestion_jobs` records processed/failed
counts, errors, start/end times, and completion status. Successful synchronization updates
`data_sources.last_synced_at`.

External product text, descriptions, configured page text, and reviews are scanned for prompt-
injection patterns. Flagged text is retained with source lineage for audit/reprocessing but marked
`QUARANTINED`; scoring and NLP consumers use only `SAFE`, `ALLOWED`, exact, fresh observations.

The richer JSONL/demo record additionally includes product name, category, description, UPC,
rating, review count, stock quantity, canonical URL, image URL, collection method, and capture
time. Nullable fields remain `null`; absent facts are not invented.

## Setup

From the repository root:

```bash
python -m pip install -r src/market_scraper/requirements.txt
python scripts/apply_migrations.py
```

For application runs, `SCRAPER_DATABASE_URL` must use the restricted `ceopro_app` role, not the
migration superuser. Configure `REDIS_URL` as shown in `.env.example`.

## Register and review a source policy

A web source can only become `ALLOWED` after explicit terms and technical-control review:

```bash
python -m src.market_scraper.policy_cli \
  --tenant-id TENANT_UUID \
  --source-id SOURCE_UUID \
  --source-url https://books.toscrape.com/ \
  --public-web \
  --terms-permit yes \
  --technical-controls-permit yes \
  --approval-reference SECURITY-TICKET-123 \
  --approved-by REVIEWER_USER_UUID \
  --retention-days 30 \
  --rate-limit 30
```

If an official API or RSS URL is supplied, the engine selects it before scraping. API/RSS sources
must be handled by their corresponding collector rather than being forced through Scrapy. Pass
`--collector google_places`, `--collector amazon_paapi`, `--collector social_data_provider`, or
`--collector scrape_creators` (in addition to the existing `standards`/`books_to_scrape`) to pick
one of the API/paid-provider collectors explicitly, and populate that source's
`connection_credentials_vault` with its required credentials before running a collection.

Each `competitor_product_mappings` row scheduled for collection must reference the reviewed
`source_id` and contain an approved `competitor_product_url`.

## Run a mapped collection

Directly execute one tenant/source job:

```bash
python -m src.market_scraper.cli \
  --tenant-id TENANT_UUID \
  --source-id SOURCE_UUID
```

Or start the background worker:

```bash
python -m src.market_scraper.worker
```

Publish requests to Redis Stream `market.scrape.requested` with string fields:

```json
{
  "tenant_id": "TENANT_UUID",
  "source_id": "SOURCE_UUID"
}
```

Messages are acknowledged only after the isolated collection subprocess succeeds. Multiple worker
processes can share the `ceopro-market-scrapers` consumer group for horizontal allocation.

## Safe demo crawl

No database is needed for demo mode:

```bash
python -m scrapy crawl books_to_scrape -a max_pages=1 \
  -O data/market/books-smoke.jsonl:jsonlines
```

Remove `-a max_pages=1` to crawl the complete 1,000-product demo catalogue. `-O` replaces the
output file, preventing accidental mixing of different observation times.

## Production reliability and observability

The collection CLI exits successfully only when the database job is `COMPLETED`; failed or
unfinalized crawls return non-zero so Redis retries them. Jobs update `heartbeat_at`, and the
`market-maintenance` service recovers stale jobs and enforces per-source retention. Prometheus
scrapes ports 9108/9109 and evaluates `market-scraper-alerts.yml` for worker outages, failure rate,
backlog, dead letters, and retention failures. The independently deployable
`market-analysis-worker` consumes safe post-collection analysis requests.

Every request and redirect is constrained to the reviewed host and its DNS answers must all be
globally routable; loopback, private, link-local, and cloud-metadata destinations are rejected.
Production must additionally enforce outbound network policy as defense in depth.

## Test

All service tests are offline:

```bash
python -m pytest src/market_scraper/tests -q

# Real migrated PostgreSQL + restricted ceopro_app RLS contract
AI_TEST_DATABASE_URL=postgresql://... APP_DB_PASSWORD=... \
  python -m pytest src/market_scraper/tests/test_market_integration_db.py -q

# Explicit one-request public canary; normal CI never depends on the internet
RUN_MARKET_LIVE_TESTS=1 \
  python -m pytest src/market_scraper/tests/test_approved_source_live.py -q
```

The tests cover parsing, policy ordering and deny-by-default behavior, URL safety, mapped tenant
lineage, validation, deduplication, PostgreSQL pipeline lifecycle, and Redis event validation.

## Live validation scripts (`scripts/`)

Every unit test above runs against a fixture, not a live vendor - real field-name/response-shape
correctness for a paid or official API can only be confirmed with real credentials, which no
environment this codebase has been developed in has ever had configured. These scripts are how that
gets checked, for real, without ever fabricating a "pass":

- **`live_credential_smoke_tests.py`** - runs ONE real API call per paid/official collector
  (ScrapeCreators, Apify, Amazon PA-API, Digi-Key, Mouser) through that collector's own real
  production code (`_initial_requests()` builds the real request, the real `parse_*` callback parses
  whatever comes back) - not a reimplementation. Reads real credentials from environment variables
  (see the script's own docstring for the exact names) and SKIPS - never fakes a result for - any
  vendor whose credentials aren't set.
- **`live_verify_retailer_domains.py`** / **`live_verify_sitemap_domains.py`** - grow
  `RETAILER_DOMAINS_BY_VERTICAL`/`SITEMAP_DOMAINS_BY_VERTICAL` only with domains actually confirmed
  live (robots.txt + a real SearchAction or sitemap), never a guessed well-known name.
- **`live_widget_diagnostic.py`** - renders a real product page with a real headless browser and
  prints real widget markup so `widget_review_*` selectors can be read off it, never guessed.
- **`live_verify_ikea_product_data.py`** - audits whether the generic `standards` collector actually
  finds price/rating/review data on a real Ikea product page (no dedicated Ikea spider exists, and
  Ikea isn't in any seed list - this is the real check before assuming it works). Amazon is
  deliberately not included here: the official `amazon_paapi` collector is the real path for Amazon,
  smoke-tested above with real credentials, not generic scraping.

All of these need real outbound internet and/or real credentials - this repository's own CI and
development sandboxes have neither, which is exactly why these are scripts to run in an environment
that does, not something bundled into the always-on test suite above.

## Adding another source

1. Confirm authorization and run the policy review.
2. Prefer an API/feed/structured-data collector when available. Google Places, Amazon PA-API,
   Digi-Key, and Mouser already have dedicated collectors (`google_places`, `amazon_paapi`,
   `digikey_api`, `mouser_api`) — just supply credentials via
   `connection_credentials_vault`, no new code needed.
3. If web collection is the approved fallback, prefer JSON-LD. Otherwise store reviewed CSS
   selectors under `data_sources.collector_config.selectors` (`product_name` and `price` are the
   practical minimum; optional fields include `currency`, `category`, `description`, `availability`,
   `image_url`, `external_id`, `rating`, `review_count`, and bounded `page_text`). Add a dedicated
   allowlisted adapter only when the source needs behavior selectors cannot express.
4. Add fixture-based offline parser tests and a bounded live smoke test.
5. Map tenant products to exact source URLs; never perform broad collection when mapped targets
   are available.
6. Never add CAPTCHA bypass, authentication bypass, credential harvesting, or private-network
   access.

Playwright should be added only for an approved source that genuinely requires JavaScript
rendering. Installing a browser runtime for a static page is expensive YAGNI cosplay.
