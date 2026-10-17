# KEEL - Staging Deployment (Render)

What this gets you: the real `ai` API service (auth, products/settings/
competitors CRUD, dashboards, RAG chat, document upload, RLS tenant
isolation) AND the real React frontend, both live at real HTTPS URLs and
wired to each other, backed by real Postgres/Redis/object storage - all
on free tiers (except the background workers), all using this repo's actual production Dockerfile
(`backend/Dockerfile.ai`) and schema/migrations, not a stripped-down
substitute. The frontend costs nothing to run continuously - Render's
free static sites don't spin down the way the free web service does.
Redis is fully self-provisioned by the Blueprint itself - nothing to set
up for it at all.

**Background workers** (competitor price collection, analysis, discovery
after a data upload, connector sync and data retention) run as one paid
Render service, `keel-workers-staging` - see "Background workers" at the
bottom. Render has no free background workers; everything else here is
free.

Every step below that needs YOU to create an account, generate a key, or
enter payment/billing info is marked **[ACTION NEEDED]**. Nothing on
this list charges money if you stay within the stated free-tier limits -
where a provider requires a card on file anyway (Cloudflare R2), that's
called out explicitly.

---

## 1. Database - Neon (Postgres) [ACTION NEEDED]

Render's own free Postgres expires after 30 days (14-day grace period) -
not viable for an ongoing environment. Neon's free tier is real,
non-expiring Postgres with `pgvector` support (this schema's own
requirement).

1. Create a free account at neon.tech.
2. Create a new project (any region close to you). Neon creates a
   default database and a default role for you automatically - that
   role has Neon's own `neon_superuser` grant, which includes
   `CREATEROLE`/`CREATEDB`/`BYPASSRLS` - exactly the admin-role shape
   this app's migration runner (`scripts/apply_migrations.py`) already
   expects (it must run as a superuser/schema-owning role, per its own
   docstring, to create the restricted `ceopro_app` role during
   migration `20260827000200_add_app_role.sql`).
3. In the Neon SQL editor, run: `CREATE EXTENSION IF NOT EXISTS vector;`
   (this schema uses pgvector for RAG embeddings).
4. Copy the connection string Neon gives you (starts
   `postgresql://<user>:<password>@<host>/<dbname>?sslmode=require`) -
   this is your `DATABASE_URL`.
5. Pick a real password for the `ceopro_app` role yourself (any strong
   random string) - this is your `APP_DB_PASSWORD`. You don't create
   this role yourself; `docker-entrypoint.sh` runs
   `scripts/apply_migrations.py` on first boot, which creates it and
   syncs its password from this exact env var.

You do **not** need to run any SQL by hand beyond step 3 - the first
deploy applies `Final_schema.sql` and all 33 migrations automatically.

## 2. Redis - fully automatic, no action needed

`render.yaml` defines its own free Key Value resource
(`keel-redis-staging`, `ipAllowList: []` - internal-only, since only
the `ai` service needs to reach it) and wires its connection string
straight into the `ai` service's `REDIS_URL` via `fromService`. Render
creates it and fills that value in the moment you import the Blueprint -
nothing to copy, nothing to paste.

## 3. Object storage - Cloudflare R2 [ACTION NEEDED]

MinIO's own client library speaks plain S3 API, and R2 is S3-compatible
- zero code changes, same `db.py::minio_client()` call, just pointed at
a different endpoint.

1. Create a free Cloudflare account, enable R2 under your dashboard.
   **Cloudflare requires a card on file to activate R2, even for the
   free tier** - you will not be charged unless you exceed 10GB storage
   or the free request quota.
2. Create one bucket (any name, e.g. `keel-staging`).
3. Create an R2 API token (R2 -> Manage API Tokens) with read/write
   access to that bucket. R2 gives you an Access Key ID, a Secret
   Access Key, and an account-specific S3 endpoint URL
   (`https://<account-id>.r2.cloudflarestorage.com`).
4. Map those to:
   - `MINIO_ENDPOINT` = the R2 endpoint URL
   - `MINIO_ROOT_USER` = the Access Key ID
   - `MINIO_ROOT_PASSWORD` = the Secret Access Key

**This is the one piece that needs a card on file, so it's fully
deferrable**: leave `MINIO_ENDPOINT`/`MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`
unset and launch without it. Every other endpoint (auth, CRUD,
competitors, dashboards, RAG chat over already-ingested data) still
works; only `/extraction/upload` and anything that touches object
storage fails until these are set - no build/deploy step breaks, it's a
per-request `RuntimeError` only when that specific feature is actually
used. Come back to this whenever you're ready to add the card.

## 4. LLM - Groq [ACTION NEEDED]

1. Create a free account at console.groq.com, generate an API key.
2. `GROQ_API_KEY` = that key. `GROQ_MODEL`/`GROQ_MAX_TOKENS` already
   have sensible defaults in `render.yaml` - no need to touch them.

Without this, every `/rag/query` chat request fails - there's no local
fallback configured in this Blueprint (`LOCAL_LLM_BASE_URL` stays
unset).

**A real limit worth knowing about**: the assistant's retrieval models
and `/sentiment/*` load local transformer models on first use. Measured
on real models (`.github/workflows/rag-runtime-check.yml`, peak resident
memory of the ai process):

| Retrieval setting | Peak | Fits free 512 MB | Fits standard 2 GB |
|---|---|---|---|
| `RAG_EMBEDDING_BACKEND=torch`, re-ranker on (code default) | 2,042 MB | no | no |
| `onnx`, `RAG_RERANKER_ENABLED=false` | 826 MB | no | yes |
| `static`, re-ranker off (what `render.yaml` sets here) | 349 MB (check), 359 MB (whole API process) | yes | yes |
| `none`, re-ranker off (keyword search only) | ~300 MB | yes | yes |

So `keel-ai-staging` on the free plan uses **semantic search with a static
multilingual embedding model**
(`sentence-transformers/static-similarity-mrl-multilingual-v1`,
Apache-2.0, Arabic included). It runs inside the ai process: no torch, no
GPU, and **no document or question leaves our own service** for embedding.
`Dockerfile.ai` downloads the model once at build time and keeps the
first 384 dimensions as a memory-mapped float16 file (the
`rag_document_chunks.embedding vector(384)` column is unchanged). Each
stored vector is labelled with the model that made it
(`embedding_model_version`). A vector from another model is never
compared with this one: it's re-embedded by `backfill_missing_embeddings`
the next time the company's index is built, so switching settings needs
no manual migration.

Verified in CI (`rag-runtime-check.yml`, job `app-e2e`). The running API
(uvicorn, migrated pgvector Postgres, Redis, MinIO built from the pinned
source) was tested over HTTP:
- sign-in;
- 4 PDF uploads through `/extraction/upload`, all `Processed` with a vector
  from this model on every chunk;
- Arabic questions about English documents (no shared word) answered by
  `/rag/query`, citing the right document;
- a company-data question citing the company's records;
- a second company that sees only its own document, both in its answers and
  in `/rag/documents`;
- API peak memory under 512 MB.

The model is weaker than the transformer models: absolute similarities are
low (0.18-0.39 for the right document), so the advisor keeps a passage
semantic search found when it scores at least
`RAG_SEMANTIC_MIN_SIMILARITY` (0.15) and within `RAG_SEMANTIC_MARGIN`
(0.05) of the best one. For better quality on a 2 GB plan, use `onnx`.
`/sentiment/*` still loads torch and is not usable on the free plan.

The answers themselves are written by Groq (`GROQ_API_KEY`). That means the
question and the retrieved passages are sent to Groq, as before. Without a
key, the assistant answers in evidence mode: the cited passages and records,
with no LLM call.

## 5. Deploy both services - Render Blueprint [ACTION NEEDED]

`render.yaml` defines both the `ai` API (`keel-ai-staging`) and the
frontend static site (`keel-frontend-staging`) - one Blueprint import
deploys both, already cross-wired: the frontend's `VITE_API_BASE_URL`
and the backend's `CORS_ALLOWED_ORIGINS`/`FRONTEND_BASE_URL` are
pre-filled with each other's deterministic `https://<name>.onrender.com`
URL (Render always serves a Blueprint service at that address) - nothing
to paste in for that part unless you rename a service or add a custom
domain later. If you do, also update the API address in the frontend's
`Content-Security-Policy` header (`connect-src` in `render.yaml`), or the
browser will refuse to call the API.

1. Push this repo to GitHub if it isn't already (it is -
   `360-Radar`), then in Render: New -> Blueprint, connect this
   repository. Render reads `render.yaml` and proposes both services.
2. `JWT_SECRET` is `generateValue: true` - Render generates a real random
   secret itself, nothing to paste in.
3. Render will still prompt you for every remaining `sync: false` env
   var before the first deploy - paste in the real values from steps 1-4
   above, plus:
   - `CREDENTIAL_VAULT_MASTER_KEY` - only if you want to test POS/ERP
     connector credential storage; generate a real one with
     `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
     (it must be a valid Fernet key specifically, not just any random
     string - `credential_vault.py` validates this and fails loudly on
     anything else). Leave blank otherwise.
   - `SMTP_*` - leave blank to keep it deferred, as you asked; every
     password-reset/verification/invite email still works, it just logs
     the real code/link instead of sending one, same behavior as today.
   - `GOOGLE_PLACES_API_KEY`/`GOOGLE_CUSTOM_SEARCH_*`,
     `SEARXNG_INSTANCE_URL` - all genuinely optional, every one degrades
     honestly (returns `[]`/nothing) when unset.
   - `SERVER_ALLOCATION_USD` - the configurable Subscription Floor Price
     placeholder from `subscription_pricing.py`; any number you want
     while there's no real hosting invoice to divide by subscriber count
     yet, or leave unset (that calculation just reports "not computed"
     until it's set, never a fabricated number).
4. Deploy. First boot runs the full schema + all migrations against
   Neon automatically (`docker-entrypoint.sh`) before the API starts -
   expect the first deploy to take longer than later ones. The frontend
   build (`npm install && npm run build`) runs independently.
5. Render's free web service (the API) spins down after 15 minutes of no
   traffic and takes up to ~1 minute to wake back up on the next request
   - normal for the free tier, not a bug. The static frontend has no
   such spin-down.

---

## Verifying it's actually live

```bash
curl https://keel-ai-staging.onrender.com/health
# {"status":"ok"}

curl -X POST https://keel-ai-staging.onrender.com/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"business_name":"Test Co","email":"you@example.com","password":"...",
       "full_name":"You","country_code":"JO","primary_currency":"JOD"}'
# real JWT back - use it as a Bearer token against /competitors, /dashboard/*, etc.
```
This is the exact sequence already verified locally against a real
Postgres instance with this exact Docker image's file layout before
this doc was written - it isn't a guess.

Then open `https://keel-frontend-staging.onrender.com` in a browser
and sign up/log in through the real UI - the build was verified locally
too (the API URL above is confirmed baked into the built JS bundle, and
`npm run build` with these exact env vars completes cleanly).

---

## Error tracking (optional)

Set `SENTRY_DSN` on the API and worker services and `VITE_SENTRY_DSN` on
the frontend (a browser DSN from the same Sentry project) to get crash
reports with the service name, environment and release. Request bodies,
cookies, credentials, query strings and user details are never sent. The
frontend's Content-Security-Policy already allows `https://*.sentry.io`.

## Uptime monitoring (optional) [ACTION NEEDED: an account]

`GET /health/ready` answers 200 when the API can reach both the database
(as the app's own restricted role) and Redis, and 503 naming which one
failed (no connection details). Point any uptime monitor at
`https://keel-ai-staging.onrender.com/health/ready` (for example a free
UptimeRobot or Better Stack check every 5 minutes) to be alerted when the
service is down. Render's own health check stays on `/health`, which only
says the process is up, so a short database blip doesn't make Render
restart a healthy API.

## Background workers [ACTION NEEDED: paid plan]

`render.yaml` defines `keel-workers-staging`: one container
(`backend/src/infrastructure/Dockerfile.market-workers`) running all five
workers under `src/market_scraper/supervisor.py`, which restarts any
worker that exits (backoff 1 s up to 60 s) and stops them all cleanly on a
deploy.

| Worker | What it does |
|---|---|
| prices | Collects competitor prices for queued collection jobs |
| analysis | Classifies collected reviews and refreshes competitor scores |
| discovery | Runs competitor discovery after a company uploads new products |
| connectors | Re-syncs each company's connected database or API on its schedule |
| maintenance | Recovers stuck jobs and applies data-retention rules |

It needs the **standard** plan (2 GB): the analysis worker's sentiment
models and the headless browser need about 1.5 GB. When the Blueprint
syncs, Render asks for:

- `SCRAPER_DATABASE_URL` - the restricted `ceopro_app` connection string
  for the same database as the API (never the admin one);
- `CREDENTIAL_VAULT_MASTER_KEY` - the same value as on the API service;
- optionally the Google / SearXNG discovery keys, the same as the API.

`SCRAPER_ACTOR_USER_ID` is preset to the database's built-in service
identity (all zeros), and Redis is wired automatically. To run only some
workers (e.g. split them across services later), set
`KEEL_WORKERS=discovery,maintenance` and so on.

The weekly discovery refresh is not a worker: it runs inside the API
service and needs nothing extra.
