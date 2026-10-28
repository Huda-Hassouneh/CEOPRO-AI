# Performance measurements

Produced with `backend/scripts/perf_baseline.py` (API phases, load) against a
locally running API. Raw results are the JSON files in this folder.

## Test conditions (all runs below)

- Machine: 4 CPU cores, 16 GB RAM (cloud dev container). Render's free web
  instance is 512 MB and 0.1 CPU, so absolute latencies there will be higher;
  these numbers are for comparing changes, not for promising production speed.
- One API process (`uvicorn src.ai.main:app`, no `--workers`), Postgres 16 and
  Redis on the same machine, object storage emulated locally.
- `API_RATE_LIMIT_ENABLED=false` so load phases measure capacity, not throttling.
- No ML models loaded (embedding/reranking/sentiment weights are not
  downloadable in this environment); the assistant uses keyword retrieval and
  the live LLM (free tier).
- Data: demo company "Zaytouna" (52,701 sales lines, 68 products) for reads and
  forecasts; uploads go into a fresh company created by the script.
- Load: virtual users each cycle through 10 main screens with 0-1 s pauses,
  spread over 5 demo companies.

## Baseline (before any optimisation) - `baseline-phases.json`

Single user, warm, 20 requests each:

| Endpoint | P50 | P95 |
|---|---:|---:|
| /alerts (bell, every page) | 265 ms | 299 ms |
| /dashboard/command-center | 257 ms | 291 ms |
| /forecasting/overview | 145 ms | 171 ms |
| /reports/sales | 120 ms | 144 ms |
| /dashboard/metrics | 58 ms | 74 ms |
| other main screens | 7-36 ms | <= 43 ms |

| Operation | P50 | P95 / max | Notes |
|---|---:|---:|---|
| Assistant, English (4 questions) | 17.1 s | 40.0 s | dominated by the LLM free tier's 429 rate-limit waits (38 s backoff) |
| Assistant, Arabic (4 questions) | 19.5 s | 26.9 s | same |
| Upload, 2,000-row .xlsx | 0.70 s | 0.81 s | |
| Upload, 10,000-row .csv | 2.4 s | 4.4 s | |
| Sales report export, PDF | 0.60 s | 0.65 s | |
| Sales report export, CSV | 2.9 s | 3.1 s | the line-level report query runs ~26 times per export |
| Forecast refresh, 68 products | 15.3 s | - | 2+ cores busy (CPU 207% mean) |

API process: 251 MB after start, peak 338 MB across these phases; at most 2
app connections held.

Most expensive queries: the forecast overview's per-product sales summary
(46 ms, 3 calls per dashboard + bell), its 90-day daily series (38 ms) and the
sales report's line query (74-81 ms). Each scans every company's `invoices`
(no `(tenant_id, issue_date)` index).

## Change 1: shared Command Center (core/tenant_cache.py)

`/alerts` rebuilt the whole Command Center, so opening the dashboard computed it
twice and every other page computed it once for the bell. It is now computed
once per company and shared for up to 30 s; any write by that company (and the
background jobs that write) clears it immediately.

Same code, cache off (`TENANT_CACHE_TTL_SECONDS=0`) vs on (30):

| | cache off | cache on |
|---|---:|---:|
| /alerts, repeated within 30 s, P50 | 228 ms | 9 ms |
| /dashboard/command-center, repeated, P50 | 197 ms | 6 ms |
| Dashboard right after a data change (both requests at once), ready P50 / P95 | 257 / 307 ms | 239 / 275 ms |
| 35 users, all requests P50 / P95 / max | 75 / 319 / 1,371 ms | 46 / 141 / 662 ms |
| 35 users, Command Center P50 / P95 | 168 / 939 ms | 30 / 510 ms |
| 35 users, /alerts P50 / P95 | 167 / 486 ms | 35 / 105 ms |
| 35 users, throughput | 56.5 req/s | 61.8 req/s |
| 35 users, errors | 0 | 0 |
| 35 users, peak memory | 281 MB | 279 MB |

Files: `cache-ttl0.json`, `cache-ttl30.json`, `load35-ttl0.json`, `load35-ttl30.json`.

## Change 2 (2026-10-28): indexes, statistics, one-sort export, shared read models, forecast validation, translations

Same script and phases, 4 CPU cores, 5 demo companies (117,000 sales lines in total), before and after on the
same machine and data: `2026-10-28-before.json`, `2026-10-28-after.json`.

| What | Why it was slow | Change |
|---|---|---|
| Index `invoices (tenant_id, issue_date)` | Every date-windowed sales query read all of the company's invoices | Migration `20261031000000`; first-sale date 23 ms -> 0.1 ms |
| Statistics after a large import | Planner statistics still described a new company as empty: the forecast staleness check took 12-33 s (nested loop over 72 M row pairs), and the import starts it | `refresh_sales_statistics()` (owner-only ANALYZE, SECURITY DEFINER) called after imports of 1,000+ rows (`STATISTICS_REFRESH_MIN_ROWS`); ~0.6 s |
| Sales CSV/JSON export | Keyset batches re-sorted the whole history once per 2,000 rows (27 sorts for 53,000 lines) | One server-side cursor: one query, one sort, streamed |
| Demand overview, dashboard metrics, financial summary, sales report page | Whole-history aggregates recomputed on every visit | Shared per company through `core/tenant_cache.py` (`cached_read`), dropped on any write by the company |
| Forecast model selection | ~560 one-step baseline predictions per baseline to use one per validation fold | Only the needed predictions (`baselines.baseline_prediction_at`); forecasts and scores byte-identical on 12 demo products |
| First load of the web app | English and Arabic translations (390 kB) in the startup bundle | Arabic loaded on demand (its own chunk); idle prefetch of all screens skipped on Save-Data / 2G |

| | Before | After |
|---|---:|---:|
| /forecasting/overview, P50 / P95 | 185 / 263 ms | 11 / 15 ms |
| /reports/sales | 225 / 380 ms | 13 / 19 ms |
| /dashboard/metrics | 87 / 118 ms | 11 / 16 ms |
| /reports/financial-summary | 52 / 79 ms | 12 / 25 ms |
| Sales report export, CSV | 5.4 s | 1.7 s |
| Sales report export, PDF | 0.82 s | 0.62 s |
| Forecast refresh, 32 products | 34.6 s | 16.8 s |
| 35 users: throughput, all requests P50 / P95 | 29.4 req/s, 628 / 1,303 ms | 48.6 req/s, 160 / 587 ms |
| 70 users: throughput, P50 / P95 | 37.1 req/s, 1,280 / 2,376 ms | 45.3 req/s, 964 / 1,947 ms |
| Peak API memory | 371 MB | 370 MB |
| JavaScript before the sign-in page renders (transferred) | 256 kB | 201 kB |

Not changed: the dashboard right after a data change (the Command Center rebuilt once, ~360 ms), and the 70-user
level, where one API process on 4 cores is CPU-bound (1 client-side connection drop in 2,788 requests; every
request the server logged returned 200). Beyond that, more API worker processes are the lever. The row-level
security function was tested as an InitPlan (`(SELECT get_current_tenant())`) and saved only ~5%, so the
policies were left as they are.

## Change 3 (2026-10-28): per-request overhead, competitor directory, compression, several workers

A CPU profile of the API under 35 users (py-spy) showed most of its time going to work around each request, not
to the request itself:

| What | Share of API CPU under load | Change |
|---|---:|---|
| A new Postgres connection (SCRAM authentication) for most requests | 21% | psycopg2's pool closes every returned connection beyond `minconn` (1): it now keeps up to `maxconn` once opened (`db_pool.py`) |
| A new Redis connection for the signed-out-token check on every request | ~15% | One shared client for per-request checks (`get_shared_redis_client`) |
| Tenant context: 4 statements at checkout and again after every commit, plus a rollback in `close()` | 13% | One statement, and re-applied only before the next statement (most connections are closed right after their last commit) |
| `/competitors` (one query per competitor for prices) | 22% | One query for all competitors (output byte-identical for every demo company); directory, discovered list and alerts shared per company until it writes |

Same script, phases and machine (4 cores) as Change 2 (`2026-10-28-round3.json`):

| | Original | Change 2 | Now |
|---|---:|---:|---:|
| 35 users: all requests P50 / P95 | 628 / 1,303 ms | 160 / 587 ms | **23 / 86 ms** |
| 35 users: throughput | 29.4 req/s | 48.6 req/s | 64.1 req/s (no longer saturated) |
| 70 users: all requests P50 / P95 | 1,280 / 2,376 ms | 964 / 1,947 ms | **246 / 1,203 ms** |
| 70 users: throughput | 37.1 req/s | 45.3 req/s | **75.2 req/s** |
| /competitors, single user | 33 ms | 32 ms | 13 ms |
| Dashboard right after a data change | 361 ms | 383 ms | 332 ms |
| Peak API memory | 371 MB | 370 MB | 363 MB |

A separate `scripts.load_test` run at 70 users with no pauses: one worker 98.5 req/s, two 110.9, four 114.9 (the load
generator and Postgres share the same 4 cores), 0 server errors in every run.

**Compression.** No API response was compressed. Responses of 1 kB or more are now gzipped (`main.py`): the ten
main screens' data 495 kB -> 72 kB, the sales report CSV download 5.4 MB -> 1.3 MB (it costs the server ~0.4 s of
CPU on that download, and saves ~1.7 s on a 20 Mbit/s connection). Built frontend files under `/assets` are now
served with `Cache-Control: immutable` for a year (`render.yaml`; not yet verified on Render itself).

**Several API workers.** `WEB_CONCURRENCY=N` (read by uvicorn) runs N processes. Each one needs about 320 MB and
keeps its own pool of up to `APP_DB_POOL_MAX_SIZE` database connections, so it is for a plan with the memory and
connection headroom - staging's 512 MB service stays at 1. The per-company read cache is now kept consistent
across processes through a generation counter in Redis: measured with 4 workers, a sale followed by 12 immediate
reads of the dashboard numbers gave 11 stale reads before this change and 0 after. The background jobs every
process starts (discovery refresh, email summaries, billing maintenance) already claim their work in the database,
so running them in several processes sends nothing twice.

**Measured and not done.** Copying the invoice date onto each invoice line would let the remaining whole-history
queries skip the join: in a rolled-back trial it made the 60-day units total 7x faster but the demand overview
only 2x and the daily series not at all - about 50 ms off the ~300 ms rebuild after a data change - while the
backfill held a lock on the invoice lines for 5.4 s at 117,000 rows. Not worth the schema change. Wrapping the
row-level-security function in a sub-select (`(SELECT get_current_tenant())`) saved ~5% and was left as is.
