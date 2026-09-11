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
  change. `collector_config["use_sandbox"] = True` points at Digi-Key's real sandbox
  (`sandbox-api.digikey.com`) — free self-registration at developer.digikey.com, no production-app
  approval gate, and Digi-Key's own docs confirm the response *structure* matches production (fake
  data, real field names) — the actual way to verify the guesses above before trusting this with
  real spend, without needing production credentials. `scripts/live_credential_smoke_tests.py`'s
  `DIGIKEY_USE_SANDBOX=1` env var drives this.
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
  (`run-sync-get-dataset-items`) — one maintained actor per platform, defaulting to Apify's own
  published actors (`apify~instagram-scraper`, `apify~tiktok-scraper`,
  `apify~facebook-pages-scraper` — the REST API requires the owner/actor-name separator to be `~`,
  not the `/` shown on the actor's store page; `_first_present()`'s candidate field names — `diggCount` for
  TikTok's like-count convention alongside `likesCount`/`like_count` — already anticipate these
  actors' real output shape, not a hypothetical one), overridable per source via
  `collector_config["actor_ids"]` for a different actor entirely. It only ever talks to the
  provider's own API host, never to facebook.com/instagram.com/tiktok.com directly — Apify (or
  whichever provider) is the one taking on the operational scraping, same category as
  `scrape_creators` below, not this codebase doing it itself. Two-stage
  collection: one call per competitor profile returns posts with their own like/share/comment-count
  aggregates, then (`collector_config["fetch_comments"]`, default on) one further call per post
  fetches the actual comment list — real text, author, and per-comment like/reply counts, landing in
  `reviews.like_count`/`reply_count` and `market_observations.like_count`/`share_count`
  (`20260906010000_add_engagement_metrics_columns.sql`). Comments are a second, separately-billed
  provider call on top of the posts call — disable `fetch_comments` for the cheaper posts-only mode.
- **`scrape_creators`** (`spiders/scrape_creators.py`) — **the reserve, cold-configured social
  provider** as of the 2026-09-07 vendor policy revision (see "Vendor policy" below — `social_data_
  provider`/Apify is the primary, active vendor for this deployment; this stayed the primary/active
  provider up to that revision, and the two share the same constructor contract so switching back is
  a credentials/config change, not a code one). [ScrapeCreators](https://docs.scrapecreators.com)
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
provider) and passed through by `cli.py` as `credentials_json`. **That column is field-level
encrypted** (`credential_vault.py`, closing `PENDING_ACTIONS.md` #42) — real envelope encryption,
not plaintext: `policy_cli.py set-credentials` (below) encrypts before writing, `data_access.py::
load_source()` decrypts after reading, and a stolen database dump alone is useless without also
compromising the separate KMS backend (`CREDENTIAL_VAULT_KMS_BACKEND` — `local`, a real working
default needing no cloud account, or `aws_kms`, the real production recommendation; see
`.env.example`). Honest framing, not oversold: this is envelope encryption at rest, not literal
"zero-knowledge" — a collector actually calling a vendor's API still needs the real plaintext in
memory at that moment, same as any system that itself makes the call. What it does guarantee: the
database and the KMS key are two separate compromises, not one.

## Vendor policy for social collection

**Revised 2026-09-07**: `social_data_provider` (Apify-shaped) is now the **primary, active**
social-data vendor — a deliberate choice for the testing phase, since Apify's free starter tier
($5/month credit) fits budget better than ScrapeCreators' pay-per-call model while validating the
pipeline. This reverses the vendor's earlier active/inactive roles (documented below for history);
nothing about *how* either collector works changed, only which one is provisioned with real
credentials. `scrape_creators` stays fully registered and tested — same "cold, ready-to-activate"
relationship Apify previously had — since a future volume/cost profile could make its per-call
billing the better fit again, and switching back is a credentials/config change, never a code one:
both collectors share the same constructor contract and yield the same item shape.

Setting this up for a real tenant — `register-source` creates the policy decision,
`set-credentials` writes the actual token (the real replacement for a raw SQL `UPDATE`, the only
way this was previously done):

```bash
# Primary: Apify (social_data_provider), active
python -m src.market_scraper.policy_cli register-source \
  --tenant-id TENANT_UUID --source-id SOURCE_UUID \
  --source-url https://api.apify.com --official-api-url https://api.apify.com \
  --terms-permit yes --technical-controls-permit yes \
  --collector social_data_provider \
  --approval-reference VENDOR-CONTRACT-REF --approved-by REVIEWER_USER_UUID --retention-days 30

python -m src.market_scraper.policy_cli set-credentials \
  --tenant-id TENANT_UUID --source-id SOURCE_UUID \
  --credentials-file /path/to/apify-token.json   # {"api_token": "<real Apify token>"}
  # or --credentials '{"api_token": "..."}' inline (lands in shell history - prefer the file form)
```

`register-source` only ever creates the *policy* row (`data_sources` itself must already exist,
created by this platform's own onboarding flow, before this runs) — it never writes credentials,
which is exactly why `set-credentials` exists as a separate step rather than one more flag on the
same command.

ScrapeCreators' source row, if created at all ahead of time, is left with `connection_credentials_vault`
empty/unset and never approved — it exists in the vault as configuration, not as a running collector,
mirroring how Apify's row was described here before this revision.

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
   genuinely no results all return `[]` — never a fabricated candidate. Three real mitigations for the
   100/day cap, all wired in by default whenever `conn` is passed (as `tenant_discovery.py` already
   does):
   - **Cache** (`search_cache.py`, `web_search_cache` table, 7-day default TTL, deliberately **not**
     tenant-scoped — identical searches across different tenants share one cache entry, since "what
     URLs does Google return for this text" is public search-index metadata, not tenant data) skips
     the live call entirely on a hit. Only a genuine Google response (including a real zero-result
     answer) is cached — a failed/errored call never is, so a temporary quota exhaustion doesn't get
     baked in as false "no results" for the cache's whole TTL.
   - **Quota pacer** (`search_quota.py`, `search_quota_usage` table, `daily_query_limit` — default
     `100`, Google's real free-tier cap) — the actual zero-dollar answer for a catalog too large to
     fit in one day's free budget. Checked *before* every real call, never after: once today's tracked
     count hits the limit, the live call is skipped for the rest of the day rather than risking an
     accidental paid overage. Pairs with `tenant_discovery.py`'s `skip_already_discovered` default
     (below) — a daily cron re-running the identical call each day naturally makes free, incremental
     progress on whatever wasn't reached yesterday, with no separate resume/queue tracking needed.
     This — not the fallback below — is the real lever for "the quota isn't enough for a large
     catalog"; deliberately not SearXNG, which needs a real running instance (self-hosted, it competes
     for RAM on the same box; a public one risks hammering someone else's free community resource with
     a whole catalog's worth of queries, which many disable their JSON API by default to prevent).
   - **SearXNG fallback** (`searxng_discovery.py`, `SEARXNG_INSTANCE_URL`) stays wired in as a genuine
     resilience fallback for a real Google outage/error — not the primary volume strategy, for the
     reason above. Raw HTML scraping of Bing/DuckDuckGo's own result pages was considered and
     deliberately excluded — see `searxng_discovery.py`'s own docstring for why (same ToS-avoidance
     precedent `social_cross_reference.py` already set for Google's result pages).
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

## Architecture C: family-keyed discovery + the 3-tier intelligence gate

The real scaling requirement agreed earlier this session: adding another customer must not multiply
scraping cost the way SKU count does (a catalog of "1 Ohm resistor, 2 Ohm resistor, ..." should not
cost N searches for N variants).

- **`product_families.py::select_family_representatives()`** groups a tenant's catalog by
  `family_key()` — a generic (not vertical-specific) heuristic stripping bare numbers and
  measurement-unit/size words, so "1k Ohm Resistor"/"2k Ohm Resistor" and "T-Shirt Small"/
  "T-Shirt Large" land in the same family. `tenant_discovery.py::discover_competitors_for_tenant()`
  (`group_by_family=True` by default) searches **once per family**, using a real, sales-volume-
  selected representative (`transactions.quantity_sold`; honestly falls back to alphabetical-first
  when no sales data exists — never silently disguised as volume-based) — then applies whatever's
  found to **every real SKU** in that family via `register_tenant_scoped_competitor()`, so
  `competitor_product_mappings` coverage is still per-SKU, just without a redundant re-search per SKU.
- **`skip_already_discovered`** (default `True`) excludes a product that already has at least one
  `competitor_product_mappings` row before family-grouping even runs — the actual mechanism behind
  "the daily quota isn't enough for the whole catalog in one run": once `search_quota.py`'s budget
  (above) is spent partway through a large catalog, the identical call re-run tomorrow (e.g. a daily
  cron) naturally skips everything already covered and makes free, incremental progress on the rest —
  no separate resume-index or queue to build.
- **`tenant_competitors.tier`** (`CANDIDATE` / `RELEVANT` / `STRATEGIC`, migration
  `20260907010000`) is computed and persisted by `competitor_classification.py::classify_competitor()`:
  `CANDIDATE` (excluded — a manufacturer, or out of region), `RELEVANT` (passed those checks, below
  the product-overlap threshold — the same as before this existed, `is_confirmed_competitor = FALSE`),
  `STRATEGIC` (passed all three — `is_confirmed_competitor = TRUE`). `product_families.py::
  recommended_collector_config(tier)` is the real point: only `STRATEGIC` gets `fetch_comments: True`
  recommended — the expensive paid-provider comment/review depth is never spent on a competitor that
  hasn't cleared the real bar, while `RELEVANT` still gets tracked and price-compared.

## Region-aware ranking: proximity + competitor breadth

Two further, real product asks this session, both additive (nothing above changes): "the competitor
must be located within the same target region... though we can ultimately rank or filter them based
on the user's preference/input", and "determine whether they are competing across most products (a
broad domain competitor) or just on a single product (a niche/item competitor)". Migration
`20260911000000` adds the columns; nothing here changes whether a competitor gets confirmed/tracked —
`tier`/`is_confirmed_competitor` above still answer that. These two are a separate axis each.

- **Competitor breadth** (`tenant_competitors.competitor_scope`) — computed and persisted by
  `competitor_classification.py::classify_competitor()` on every run, alongside tier:
  `NICHE_ITEM` (this competitor's mapped-product count is `<= 1` — literally "just on a single
  product"), `BROAD_DOMAIN` (product-overlap ratio clears `broad_domain_threshold`, default `0.5`,
  its own parameter — not forced to equal the confirmation `threshold`, though they share the same
  default value), `PARTIAL_OVERLAP` for the real, honest middle ground. A `NICHE_ITEM` competitor can
  still be `STRATEGIC` tier (the one product they carry is an exact, in-region, non-manufacturer
  match) — "real but narrow" is a genuine outcome, not a contradiction between the two axes.
- **Proximity** — `companies.latitude`/`longitude` (set via `company_geo_profile.py::
  set_tenant_search_scope()`, a partial-update function: a call updating just the scope level
  doesn't require re-sending the tenant's country list or coordinates) and `global_competitors.
  latitude`/`longitude` (populated by a discovery source that has real coordinates to offer — e.g. a
  future Google Places nearby-search result; `discovery.py::CandidateSource.latitude/longitude` carry
  this through today, though the only discovery source wired in so far, product-keyed Custom Search,
  never sets them). `geo.py::haversine_km()` (pure stdlib, no geocoding API) computes real
  great-circle distance whenever BOTH sides are known; `classify_competitor()` persists it as
  `tenant_competitors.distance_km` — `NULL`, never a fabricated `0`, when either side's location is
  unknown.
- **The radius is never a number the end user types.** `companies.search_scope_level` (`CITY` /
  `PROVINCE` / `COUNTRY` / `CUSTOM`, default `PROVINCE`) is the real UI-facing control — a
  dropdown/segmented choice, not a "how many kilometers?" field nobody can answer intuitively.
  `set_tenant_search_scope()` resolves the actual `default_search_radius_km` server-side:
  `SCOPE_LEVEL_PRESET_RADIUS_KM` maps `CITY`→25km/`PROVINCE`→150km; `COUNTRY` explicitly clears the
  radius to `NULL` (region becomes "this tenant's whole `operating_countries` list", not a distance
  ring at all); `CUSTOM` is the one deliberate escape hatch for an advanced/API caller who wants an
  exact km figure, and requires `custom_radius_km` be passed alongside it (rejected otherwise).
- **Multi-country scope** — `companies.operating_countries` (pre-existing) is what
  `set_tenant_search_scope()` writes a user's multi-country input into; `competitor_classification.py
  ::_in_operating_region()` already checked it before this session's changes, so a tenant with several
  operating countries was already correctly excluding sellers outside all of them, not just the
  primary one.
- **Ranking/filtering at query time, not at classification time** —
  `data_access.py::list_tenant_competitors_by_proximity(conn, tenant_id, radius_km=None,
  scope=None, limit=None)` sorts every tracked competitor closest-to-farthest (unknown distance
  always sorts last, never first), optionally filtered to one `competitor_scope` and/or a
  `radius_km` cap. Distance/scope are computed once by `classify_competitor()` and just sorted here —
  this is deliberately a read-time choice, not baked into `is_confirmed_competitor`, so "expand or
  narrow the search radius from the interface" is exactly widening/narrowing `radius_km` on this call
  (or, to change the tenant's *standing* default rather than one request, `companies.
  default_search_radius_km` via `set_tenant_search_scope()` — `sector_detection.py::
  resolve_tenant_search_radius()` resolves whichever the caller wants: an explicit per-call
  `override_km`, falling back to the tenant's stored default, falling back to `None` — never an
  invented number). Widening the radius later never requires a new discovery run: it just admits more
  of the already-computed rows.

## Domain-level discovery: competitors by industry, not just by exact product match

Product-level discovery above (`discover_competitors_for_tenant()`) can only ever find a seller
already seen carrying something the tenant also sells — a same-industry rival with a genuinely
different product mix is structurally invisible to it. `tenant_discovery.py::
discover_domain_level_competitors_for_tenant()` is the fix: two real, combined ("hybrid") sources,
neither requiring a product name at all —

- **`places_nearby_discovery.py::discover_nearby_places()`** — official Google Places Nearby Search
  around the tenant's own `companies.latitude`/`longitude` (only runs when both a Places API key and
  tenant coordinates are on file), for the tenant's detected industry keyword
  (`sector_detection.py::VERTICAL_INDUSTRY_LABELS`). Radius comes from the tenant's own
  `search_scope_level` (see above), clamped to Google's real, hard `50km` Nearby Search cap
  (`MAX_NEARBY_SEARCH_RADIUS_KM`) — flagged, not silently exceeded. A result with no real `website`
  field (common for small local businesses) is skipped, never guessed at; a result that does have one
  carries its own real coordinates (`geometry.location` from Place Details, not the search center),
  so `classify_competitor()` computes a genuine, per-competitor `distance_km`.
- **`web_product_discovery.py::discover_industry_candidates()`** — the same Google Custom Search
  API/cache/quota-pacer/SearXNG-fallback machinery `discover_product_candidates()` already uses, but
  queried with `sector_detection.py::build_industry_search_query()` ("electronics store buy shop
  store price Jordan", not a product name) — always attempted, since it needs no coordinates, only
  the tenant's detected vertical.

Every real candidate from either source is registered via **`discovery.py::
register_domain_level_competitor()`** — deliberately **no** `competitor_product_mappings`/
`data_sources` row at registration time (there's no specific product page to scope a collection job
to yet, only a business identity), but a real, classified `tenant_competitors` row. `classify_competitor()`
(`src/ai/pricing/competitor_classification.py`) already knows how to confirm one of these: for a
domain-sourced competitor with zero product mappings, passing the manufacturer/region checks *alone*
is the confirmation bar — requiring product overlap here would make domain-level discovery pointless,
since nothing it finds would ever have any. Its `competitor_scope` is `BROAD_DOMAIN`, not `NICHE_ITEM`
— it was found *by being* a same-industry business, not by carrying one SKU.

**Closing the loop — "scrape data from their website if they have one":** immediately after a domain
find is **confirmed**, `discover_domain_level_competitors_for_tenant()` calls
**`map_products_on_domain_competitor_site()`** — real, zero-API-cost product discovery scoped to
that ONE known competitor's own domain, combining `direct_search.py::search_product_across_retailers()`
(schema.org SearchAction) and `sitemap_discovery.py::discover_products_via_sitemap()` (sitemap.xml).
Both functions are domain-agnostic at the call site — the hand-seeded `*_BY_VERTICAL` dicts elsewhere
are only an optimization for "which domains to try" when the domain isn't already known, irrelevant
here since it is. Any real product match registers through the **ordinary product-level path**
(`register_tenant_scoped_competitor()`) — `website_identity_key` dedup converges it onto the exact
same `global_competitors` row `register_domain_level_competitor()` already created (proven directly:
`test_domain_and_product_level_finds_converge_on_the_same_competitor_row`), and — unlike the
domain-level registration — creates the real `competitor_product_mappings`/`data_sources` rows
`load_scrape_targets()` requires. A confirmed domain-level competitor with a real product match is,
from that point on, indistinguishable from one product-level discovery found directly: it flows into
the same `standards` collector (`market_source.py`'s JSON-LD/microdata/widget-CSS layers), the same
Tier-2 staging/validation/safety pipeline, the same policy-approval gate before any real collection
runs. This never runs for an excluded manufacturer or out-of-region find — no point spending the
crawl effort where `classify_competitor()` already said no. `tenant_competitors.discovery_method`
(`PRODUCT_SEARCH` / `PLACES_NEARBY` / `INDUSTRY_KEYWORD_SEARCH`) records whichever path found the
*competitor itself* first and is never overwritten by a later, different-path find — independent of
how its products get mapped.

**Known, flagged gap**: `global_competitors.industry_sector` backfill for a competitor already found
by product-level discovery (inferring their industry from name/page text, `sector_detection.py::
infer_industry_sector()` is built and tested standalone) isn't yet wired into an automatic batch job —
it's a real, callable function, just not yet scheduled to run over existing rows.

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

## Live client database sync (real-time, not file-based-only)

`connector_sync.py` is the real fix for "we are NOT building a static reporting tool - a
file-based-only system is completely rejected": a client's Postgres-compatible database can be
registered as a **live, polled connector** instead of requiring a file re-upload for every
update.

- **`policy_cli.py register-source --collector db_connector`** registers one, same policy-review
  gate as every other source (`--terms-permit`/`--technical-controls-permit`/`--approval-reference`
  — a connector is never synced just because a row exists for it). `collector_config` (JSONB) holds
  `{"host", "port", "dbname", "query", "field_mapping"}` — the query and column names are the
  tenant's own configuration, same as any other explicit integration. `set-credentials` writes the
  client database's `{"user", "password"}` — encrypted, see below.
- **`connector_sync.py::sync_db_connector_source()`** runs one real sync: opens a **read-only**
  connection to the client's database (`.set_session(readonly=True)` — real defense-in-depth, this
  module is a reader and must never be able to write to a client's production database), runs the
  configured query (`db_adapter.py::read_db_query()`), and feeds the results through the exact same
  `ingestion_pipeline.process_records()` every file upload already uses — same savepoint-per-row,
  nothing-silently-dropped guarantee, `trusted_field_mapping` (the caller already knows its own
  schema, no header-guessing needed). `data_sources.last_synced_at` (a real, pre-existing column)
  only advances on success — a failed sync is retried next cycle, never marked as if it succeeded.
- **`run_due_connector_syncs(conn, tenant_id)`** — the real scheduler entry point, call it on an
  interval (a cron/beat task). Each due source is a real, independent attempt; one source's failure
  never blocks another's.
- **`DEFAULT_SYNC_INTERVAL_MINUTES = 15`** — a real trade-off, not arbitrary: near-real-time enough
  that an inventory/price change is reflected within a quarter hour (materially useful for a
  stockout alert or a price recommendation), without hammering a client's production database every
  few seconds. `data_sources.sync_frequency_minutes` (pre-existing column) is per-source, not
  uniform — set it tighter for a high-velocity POS, looser for a slow-moving catalog.

**Scope, stated plainly**: this pass covers a Postgres-compatible client database. An API connector
(POS/ERP vendor REST APIs) reuses the exact same scheduling/watermark mechanism, just with a
per-vendor `fetch_page()` (`api_adapter.py`'s existing contract) instead of a SQL query — there's no
way to poll an arbitrary REST API without knowing its pagination shape. A true multi-dialect DB
driver (MySQL, SQL Server, Oracle, ...) — the "Universal Connector Layer" for the top Middle East
POS/ERP systems — is a distinct, larger piece of work, not built in this pass.

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
python -m src.market_scraper.policy_cli register-source \
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
`--collector google_places`, `--collector amazon_paapi`, `--collector digikey_api`,
`--collector mouser_api`, `--collector social_data_provider`, or `--collector scrape_creators` (in
addition to the existing `standards`/`books_to_scrape`) to pick one of the API/paid-provider
collectors explicitly, then populate that source's credentials with
`policy_cli.py set-credentials` (see "Vendor policy for social collection" above) before running a
collection.

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

## Automatic competitor discovery (production-hardening audit fix)

Until this fix, `tenant_discovery.py`'s discovery orchestration (`discover_competitors_for_tenant()`,
`discover_domain_level_competitors_for_tenant()`) was fully built and correctly wired internally, but
**nothing in the live system ever called it** — only integration tests did. Production discovery was
100% a manual `policy_cli.py`/CLI operation, despite in-repo documentation describing an automatic
"client uploads a file → the engine searches for competitors" flow.

`discovery_worker.py` closes that gap:

```text
POST /extraction/upload (src/ai/main.py) persists new products
        ↓ only when new products were actually created
Redis stream: market.discovery.requested — {"tenant_id": ...}
        ↓
discovery_worker.py::discover_for_tenant()
        ↓
tenant_discovery.discover_competitors_for_tenant() + discover_domain_level_competitors_for_tenant()
        ↓
enqueue_collection() for any result whose policy_status is ALREADY 'ALLOWED'
```

**Does not bypass the human policy-approval workflow.** A fully automated discovery run never
supplies `terms_evidence`, so `policy.py::evaluate_source()` can only ever return `RESTRICTED` for a
brand-new source — `ALLOWED` requires `terms_evidence`, which only the existing manual approval step
(`data_access.record_policy_decision`'s approval fields) ever supplies. `discovery_worker.py` only
auto-enqueues collection for a result whose `policy_status` **already** reads `ALLOWED` — meaning a
human already approved that exact website for a different product, and discovery just found it also
carries one of the tenant's newly-uploaded products. That extends an already-approved site's coverage
to a new product mapping; it never auto-approves a genuinely new, unreviewed source.

Start the worker the same way as the others:

```bash
python -m src.market_scraper.discovery_worker
```

Same attempt-tracking/dead-letter/reclaim contract as `worker.py`/`analysis_worker.py`
(`DISCOVERY_MAX_ATTEMPTS`, `DISCOVERY_DEAD_STREAM_KEY`, `DISCOVERY_CLAIM_IDLE_MS` — see `.env.example`).

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
