# CEOPRO AI — Web Crawling / Data Collection Layer

This service implements Part 2 of the Real-Time Market Analysis Pipeline. It collects public
market data, normalizes it into stable records, validates it, and exports newline-delimited JSON
(JSONL) for downstream cleaning, entity extraction, price intelligence, and forecasting.

The repository's `target.txt` points to `https://toscrape.com`. The first approved source is its
static product catalogue, **Books to Scrape**. It is intentionally safe for crawler development.
Real competitor sites should get separate spiders because selectors and collection permissions
are source-specific; cramming every website into one mega-spider would be brittle nonsense.

## Collected fields

Each product observation includes:

- source name/type/policy status and exact-data flag;
- external ID (UPC), product name, category, description;
- current/original price, ISO currency, and discount percentage;
- availability text, stock status, and published stock quantity;
- rating and review count;
- canonical product/image URLs and UTC capture timestamp.

Nullable fields stay `null`; they are never invented. The output is raw collection data, not an AI
prediction.

## Safety defaults

- stays on the explicitly approved `books.toscrape.com` domain;
- honors `robots.txt`;
- identifies itself with a crawler user agent;
- uses per-domain concurrency limits, delay, AutoThrottle, timeout, and bounded retries;
- sends no cookies, logs in nowhere, and bypasses no access controls;
- rejects malformed records and removes duplicates within each run.

## Setup

From the repository root, create/activate a virtual environment and install only this service's
dependencies:

```bash
python -m pip install -r src/market_scraper/requirements.txt
```

## Run

Create an output directory, then crawl the complete catalogue (approximately 1,000 records):

```bash
python -m scrapy crawl books_to_scrape -O data/market/books.jsonl:jsonlines
```

For a fast smoke test, stop after the first catalogue page:

```bash
python -m scrapy crawl books_to_scrape -a max_pages=1 \
  -O data/market/books-smoke.jsonl:jsonlines
```

`-O` replaces that output file so repeated runs do not silently mix observations from different
capture times. Use `-o` only when append semantics are explicitly wanted.

Useful spider arguments:

| Argument | Default | Purpose |
|---|---|---|
| `start_url` | `https://books.toscrape.com/` | Approved seed URL; other domains are rejected |
| `source_name` | `Books to Scrape` | Source/competitor label in every record |
| `max_pages` | unlimited | Bound catalogue pagination for smoke tests |

## Test

Tests are offline and make no network requests:

```bash
python -m pytest src/market_scraper/tests -q
```

## Downstream integration

JSONL is the collection boundary. A later mapping/persistence job should resolve each external
product to a tenant's `competitor_product_mappings` row before inserting observations into
PostgreSQL `competitor_prices`. The crawler deliberately does not guess tenant IDs or product
mappings. That preserves multi-tenant isolation and the repository's service-ownership contract.

Dynamic telecom pages can be added with a dedicated `scrapy-playwright` spider only when a
specific approved source actually requires browser rendering. Playwright is not installed for this
static target: unused browser dependencies add hundreds of megabytes and violate YAGNI with
spectacular enthusiasm.
