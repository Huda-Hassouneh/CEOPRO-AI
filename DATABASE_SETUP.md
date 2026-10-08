# Connecting the AI service to a database

The AI service (`src/ai/main.py`, the forecasting consumer and the market
workers) reads every connection string from the environment. Nothing is
committed: put real values in `.env` (git-ignored) locally, or in the
hosting provider's environment settings.

## Local development (unchanged)

`docker compose up` with `.env` copied from `.env.example`. `DATABASE_URL`
is the superuser (migrations only); `scripts/apply_migrations.py` creates the
schema and the restricted `ceopro_app` role, whose password is
`APP_DB_PASSWORD`. Leave `APP_DATABASE_URL` empty.

## Shared test database on Render (AI team user)

The web backend (`backend` branch) creates and migrates this database with
`prisma migrate deploy`. The AI team has its own user, given in the team's
connection document (database, user, host, port, password; SSL required).
That user is **not** an owner: it has SELECT/INSERT/UPDATE on 16 tables and
INSERT on `audit_logs`, nothing else, and row-level security applies.

### Configure

Build the connection string from the document as
`postgresql://<user>:<password>@<host>:<port>/<database>?sslmode=require`
(URL-encode the password if it contains `@ : / ? # %`) and set it as:

| Variable | Value |
|---|---|
| `APP_DATABASE_URL` | the connection string - every tenant request uses it as-is |
| `SCRAPER_DATABASE_URL` | the same value (market workers) |

Do **not** point `DATABASE_URL` at it: that variable is the migration /
admin connection, and the processes that use it (extraction consumer,
watchdog, demo seeding) need privileges this user doesn't have.
`APP_DB_PASSWORD` is not needed when `APP_DATABASE_URL` is set.

Use the **External** hostname from outside Render, the **Internal** one from
a service running on Render in the same region.

### Check before use (read-only, prints no credentials)

```bash
python scripts/check_database.py \
  --expect-database <database from the document> \
  --expect-user <user from the document> \
  --tenant-id <a test account's tenant_id> --user-id <that account's user_id>
```

It confirms the database and user, SSL, that the user can't bypass RLS, the
privileges on every table and sequence, reads each accessible table under
the tenant context (the same `set_config(..., true)` pattern the document
describes and `src/infrastructure/db_pool.py` uses), and lists the
AI-specific schema objects that are missing.

### What works with the current grants

Verified 2026-10-08 against a replica built from the backend's own
`prisma/migrations` with a user given exactly the document's grants:

| Works | Fails until the owner acts |
|---|---|
| Connecting through `src/ai/db.py`'s pool; tenant context kept across commits; other tenants' rows hidden | Anything reading `products`, `companies`, `invoices`, `invoice_items`, `transactions`, `inventory`, `demand_forecasts`, `currency_rates`: dashboard, forecasting, pricing, insights, RAG summaries, discovery's company profile |
| Reading all 16 granted tables under a tenant context | Writing staged import rows: no USAGE on `import_staging_rows_staging_row_id_seq` |
| Private (per-tenant) competitors and tenant competitor links, RAG document metadata, data sources and ingestion jobs, audit log entries | Re-indexing a RAG document: no DELETE on `rag_document_chunks` |
| | Discovery and market collection writes: the AI-only columns below don't exist yet |
| | Search cache / quota, cost ledger, alert rules and events, model versions, recommendation outcomes, extraction promotion: no grants |

`src/infrastructure/database/render_ai_user_grants_request.sql` lists the grants each feature
needs, for the database owner to review and apply.

### Migrations

Do **not** run `scripts/apply_migrations.py` against the Render database: it
refuses when it finds Prisma's `_prisma_migrations` table (its files are
already in the Prisma history under other names), and the AI user couldn't
run DDL anyway.

Seven AI migrations have no Prisma counterpart, and the Prisma-built schema
lacks what they add:

- `20260911000000_add_geo_proximity_and_competitor_scope.sql`
- `20260911010000_add_rag_documents_bucket_path_unique_index.sql`
- `20260911020000_add_rag_documents_content_hash.sql`
- `20260912000000_add_connector_discovery_function.sql`
- `20260913000000_add_reply_threading_to_reviews.sql`
- `20260913010000_add_video_metadata_columns.sql`
- `20260915000000_add_scraping_cost_ledger.sql`

They are additive (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE/INDEX IF NOT
EXISTS`, `CREATE OR REPLACE FUNCTION`) and safe on a live database. They
belong in the backend's `prisma/migrations`, deployed by the schema owner.

### Tenant isolation note

On the Prisma-built schema `get_current_tenant()` returns whatever
`app.current_tenant_id` is set to, without checking that
`app.current_user_id` is a member of that tenant (the older
`Final_schema.sql` version checked). Isolation therefore rests on the
caller: the AI service must only ever set tenant and user IDs taken from a
verified JWT or a trusted job payload, never from request parameters.

### Never

- Commit a connection string or password (`.env` is git-ignored).
- Run `seed_demo_data.py` or `apply_migrations.py` against the shared database.
- Connect the app with a superuser or `BYPASSRLS` role.
