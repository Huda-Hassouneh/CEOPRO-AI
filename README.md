# CEOPRO AI - Phase 1 Complete Infrastructure Blueprint

This directory contains the production-grade foundation architecture for **CEOPRO AI Phase 1**.

## 1. Managed Technical Services (Item 1.1)
- **PostgreSQL**: Relational storage engine with multi-tenancy logical partitioning (Port `5432`).
- **Redis**: Low-latency cache memory, rate-limiter, and async transaction status coordinator (Port `6379`).
- **MinIO**: S3-compatible cloud-ready storage for raw file ingestions and model weights (Ports `9000/9001`).

## 2. Infrastructure Operations Command Checklist
Use these native Docker Compose commands to manage the infrastructure locally:
- **Launch Services Asynchronously**: `docker compose up -d`
- **Verify Operational Container States**: `docker compose ps`
- **Inspect Infrastructure Logs**: `docker compose logs -f`
- **Strict Data Reset (Wipe Volumes)**: `docker compose down -v`

## 3. Deployment Schemas & Specifications Attached
- `init_schema.sql`: Production-ready PostgreSQL tables establishing multi-tenancy isolation via the explicit `tenant_id` foreign keys (Item 1.2).
- `REDIS_ARCHITECTURE.md`: Technical documentation defining memory expiration keys and tracking patterns (Item 1.3).
- `MINIO_STORAGE_ARCHITECTURE.md`: Target bucket isolation rules and file storage paths (Item 1.4).
- `DATA_OWNERSHIP_AND_CONTRACTS.md`: Explicit microservice permissions matrix and data-transfer payloads (Items 1.5 & 1.6).
- `.env.example`: Secure production-safe template configuration file (Item 1.7).
- `check_connectivity.py`: Python automation health check confirming real-time connections pass successfully (Item 1.8).

## 4. Web Crawling / Market Data Collection
The standalone scraper service lives in [`src/market_scraper/`](src/market_scraper/README.md).
It implements deny-by-default collection policy decisions, Redis worker allocation, tenant-scoped
product mappings, respectful Scrapy collection, ingestion-job tracking, canonical PostgreSQL
`competitor_prices` persistence, JSONL demo output, and offline tests. The repository's approved
`toscrape.com` target remains the source-specific development fixture.

```bash
python -m pip install -r src/market_scraper/requirements.txt
python -m scrapy crawl books_to_scrape -a max_pages=1 -O data/market/books-smoke.jsonl:jsonlines
```

## 5. Run Connectivity Health Check
To prove real-time access before handing over to Web App and AI teams, run:
```bash
pip install psycopg2-binary redis
python check_connectivity.py
```

## 6. Mock Infrastructure Spin-Up (One-Command Quickstart)
To spin up the entire isolated technical mock environment and seed the data broker streams in one continuous workflow execution, run the following unified command:
```powershell
docker compose up -d; python src/infrastructure/init_broker.py; python src/infrastructure/check_connectivity.py
```

## 7. Scraping Cost Ledger & Dynamic Cost-to-Margin Gate
Every real scrape attempt is money spent, and low-value products can't absorb that cost forever.
`src/market_scraper/cost_ledger.py` protects margins with two checks run before a scrape is
enqueued (`enqueue.py`), both against a real `scraping_cost_ledger` table that
`persistence.py`'s `PostgresPricePipeline` writes to automatically for every attempt, promoted or
quarantined:

- **Dynamic cost-to-margin ratio** (`COST_GATE_MAX_RATIO`, default `0.20` / 20%, looked back over
  `COST_GATE_WINDOW_DAYS`, default 30) - blocks a product once its trailing known scraping cost
  reaches that percentage of its real margin (`current_price - cost_price`, or `current_price`
  alone when no cost price is on file). This scales automatically with each product's own value
  instead of a flat dollar rule, and always **allows** when there isn't yet enough real data to
  judge (no product record, no cost data, no positive price/margin) - insufficient data is never
  treated as over budget.
- **Minimum product price floor** (`COST_GATE_MIN_PRODUCT_PRICE`, default `1.00`) - a hard baseline
  checked *before* the ratio or the ledger are even queried. Heavy operational, distribution, and
  team overhead means tracking a product priced (or margined) below this floor can never yield real
  profit, no matter how cheap the scraping cost is - so the gate blocks it immediately, from day
  one, with zero ledger rows needed. A product must clear the floor before the ratio is even
  evaluated.

Per-collector costs are configured per paid vendor via `SCRAPE_COST_PER_REQUEST_<COLLECTOR>` env
vars with no baked-in defaults (an unconfigured collector's ledger rows record `cost_amount = NULL`
- honestly unknown, never a fabricated `$0.00`). Server/hardware depreciation, electricity, and
marketing spend are deliberately excluded from this formula - they're real costs, but period costs
and (for marketing) customer-acquisition cost, not per-request cost-of-service, so they belong in a
separate periodic margin report rather than a live per-scrape gate. Full details, the env var list,
and the underlying reasoning live in
[`src/market_scraper/README.md`](src/market_scraper/README.md#scraping-cost-ledger-and-the-dynamic-cost-to-margin-gate-cost_ledgerpy).
