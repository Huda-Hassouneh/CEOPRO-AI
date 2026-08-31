# Scaling the Extraction Pipeline to Large Files

This documents a real, measured performance finding from a live validation run and how to fix
it when higher-throughput infrastructure ("more cores, more/faster DB capacity") is available.
Nothing in this document has been implemented yet — it's a plan, not a claim.

## What was measured

Live test: `mocks/Electronics_For_Test.xlsx`, 51,947 rows, run through the real production path
(`ingestion_pipeline.process_records()`, the same function `POST /extraction/upload` calls) —
2026-08-31. Full raw results: `reports/extraction/electronics_for_test/`.

| Run | Rows | DB involved | Time | Throughput |
|---|---|---|---|---|
| Pilot (first 300 rows, live Postgres) | 300 | yes | 1.2s | 255 rows/sec |
| Full file, live Postgres, per-row `SAVEPOINT` | 51,947 | yes | **8.5 hours** | 1.7 rows/sec |
| Full file, `conn=None` (dry run) | 51,947 | no | **7.0 seconds** | 7,424 rows/sec |

The 300-row pilot and the CPU-only dry run agree with each other (same order of magnitude,
same code). The full DB run is ~4,400x slower than the CPU-only run on the *identical* rows.
That gap is the entire story — extraction logic itself (regex, typed parsing, catalog matching)
is not the bottleneck at any scale tested here.

## Root cause

`ingestion_pipeline.py::_execute_in_savepoint()` wraps every single-row database write in
`SAVEPOINT ...; ...; RELEASE SAVEPOINT ...`, and every row does two such writes (the initial
`import_staging_rows` insert, then a status update). That's correct and necessary for the
guarantee it protects — see `PENDING_ACTIONS.md` #39 — but it happens inside **one long-lived
transaction** for the whole file (`process_records()` never calls `conn.commit()` until every
row is done).

PostgreSQL tracks subtransactions (which is what a `SAVEPOINT` creates) in a fixed-size
per-backend cache (64 entries by default). Once a transaction exceeds that many subtransactions,
every subsequent visibility check has to consult the on-disk `pg_subtrans` SLRU instead of the
in-memory cache — and that lookup gets slower as the subtransaction count grows, because it has
to walk the chain back to find the top-level transaction's status. A file with 51,947 rows × 2
savepoints = ~104,000 subtransactions in one transaction is deep enough into this regime that
per-row cost visibly climbs across the run, not just once at the 64-entry mark. This is a
well-documented PostgreSQL characteristic, not a bug in the savepoint logic itself — the logic
is correct, the *transaction shape* around it is what doesn't scale.

## How to scale it (in priority order)

### 1. Batch commits — the fix that matters, no new infrastructure needed

Commit every N rows (e.g. 500–2,000) instead of once per file. This resets the subtransaction
count periodically, so no single transaction ever approaches the cliff. The atomicity guarantee
weakens slightly — a crash mid-file loses at most the current uncommitted batch, not zero rows,
versus today's all-or-nothing per file — but every row's own `SAVEPOINT`-protected write is
still individually safe, and the zero-data-loss guarantee (the raw row lands in
`import_staging_rows` before parsing is attempted) is unaffected either way.

This alone should recover close to the 7,424 rows/sec CPU-bound ceiling, bounded by actual
Postgres write throughput per batch rather than by subtransaction depth. No cluster, no extra
hardware — this is the fix to do first, on the infrastructure that exists today.

### 2. Bulk writes instead of one-row-at-a-time INSERT/UPDATE

Batch the `import_staging_rows` inserts with `psycopg2.extras.execute_values` (one round trip
per batch instead of one per row) rather than a single-row `INSERT ... RETURNING` per row.
Combined with #1, this cuts network round-trips by roughly the batch size, which matters more
as DB latency increases (a remote/managed Postgres instance, not just local Docker).

### 3. Horizontal parallelization — for genuinely large files, on genuinely larger hardware

The CPU-only run above confirms row processing is embarrassingly parallel: each row's
`_process_mapped_row`/`_process_fallback_row` call is a pure function of that row alone, no
shared mutable state between rows. On a multi-core machine (or a multi-node cluster — this is
the "supercomputer" case):

- Split `rows` into N shards, one Python process (or worker node) per shard, via
  `multiprocessing.Pool` for a single large machine, or a distributed job queue (the repo
  already has a Redis Stream consumer pattern in `src/market_scraper/worker.py` — the same
  shape applies here: one job per file, one message per row-batch) for a real cluster.
- Each worker opens its own DB connection and applies fix #1 (batched commits) independently —
  workers don't need to coordinate with each other, since `import_staging_rows`/
  `ingestion_jobs` writes are all per-row/per-job, not cross-row aggregations.
- Expected scaling: near-linear with worker count up to the point where Postgres write
  throughput (not CPU) becomes the bottleneck again — at which point #1/#2 on the DB side, not
  more workers, is the next lever.
- `ingestion_jobs.rows_processed/rows_partial/rows_failed` (already atomic per-statement `UPDATE
  ... SET x = x + %s`, see `_update_job_counts()`) already tolerate concurrent workers updating
  the same job row — no schema change needed for this part.

### 4. Bound memory for files larger than this one

`file_dispatch.read_source_file()` currently loads every row into memory as a list of dicts
before processing starts. Fine at 51,947 rows × 8 columns (a few hundred MB at most); would need
revisiting — a generator-based adapter reading in chunks — for a file with millions of rows or
significantly more columns. Not a problem this test file's scale actually exercised, flagged for
when it becomes relevant rather than solved speculatively now.

## What this document is not

This is a plan for when higher-throughput infrastructure is available and large files become a
real, recurring use case — not an implementation done in this pass. The one fix actually applied
alongside this document is unrelated to performance: a `HEADER_SYNONYMS` gap (`total price`,
`date time` weren't recognized) that this same live test also found, which was causing this file
to fall to weak `FALLBACK` extraction regardless of speed. See `PENDING_ACTIONS.md` for both
findings tracked individually.
