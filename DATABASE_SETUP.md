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

## Hosted database on Render (AI team user)

The shared database on Render is created and migrated by the web backend
(the `backend` branch, `prisma migrate deploy`). The AI team has its own
database user. Set:

| Variable | Value |
|---|---|
| `APP_DATABASE_URL` | the AI team user's **External** connection string from Render (from outside Render) or **Internal** (from a service on Render in the same region), with `?sslmode=require` |
| `SCRAPER_DATABASE_URL` | the same value |
| `DATABASE_URL` | the same value; used by the extraction consumer, watchdog and demo seeding |

`APP_DB_PASSWORD` is not needed when `APP_DATABASE_URL` is set.

Then check the database **before** starting anything - read-only, prints
no credentials:

```bash
python scripts/check_database.py            # reads APP_DATABASE_URL
```

It reports the connection (SSL, user, version), whether the user bypasses
row-level security (it must not), the migration history, every table with
this user's privileges and RLS state, and the objects the AI-only
migrations add.

### Migrations

Do **not** run `scripts/apply_migrations.py` against the Render database -
it refuses when it finds Prisma's `_prisma_migrations` table, because its
files are already in the Prisma history under other names and replaying
them would re-run non-idempotent DDL. Seven AI migrations
(`20260911000000` ... `20260915000000` in `src/infrastructure/database/migrations/`)
have no Prisma counterpart yet; if `check_database.py` lists them as
missing, they need to be added to the backend's `prisma/migrations` and
deployed by whoever owns the schema there. They are all additive
(`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE/INDEX IF NOT EXISTS`,
`CREATE OR REPLACE FUNCTION`), so applying them to a live database is safe.

### Never

- Commit a connection string or password (`.env` is git-ignored).
- Run `seed_demo_data.py` against the shared database.
- Connect the app with a superuser or `BYPASSRLS` role: tenant isolation
  depends on row-level security.
