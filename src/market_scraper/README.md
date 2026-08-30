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
sites; a giant conditional mega-spider would be neither reliable nor maintainable.

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
must be handled by their corresponding collector rather than being forced through Scrapy.

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

## Adding another source

1. Confirm authorization and run the policy review.
2. Prefer an API/feed/structured-data collector when available.
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
