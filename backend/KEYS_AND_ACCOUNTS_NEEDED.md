# Keys, tokens and accounts KEEL really uses - fill-in checklist

Checked against the code on `KEEL_Test` (every name below is one the backend or
frontend actually reads). **Every value is blank on purpose: never write a real
value in this file or any committed file - this repository is public and git
history is permanent.** Put real values in:

- your local `backend/.env` (git-ignored) for development, and
- Render -> each service -> **Environment** for staging/production.

Legend: **REQUIRED** - **FREE** - **PAID** (card or paid plan) - **YOU GENERATE**
(no account; you create the value).

> **If a real value was ever committed here, treat it as stolen: revoke it at the
> provider and create a new one.** Editing the file does not remove it from git
> history or from anyone who already copied it.

---------------------------------------------------------------------------

## 1. Secrets you generate yourself - REQUIRED

```
JWT_SECRET=
POSTGRES_PASSWORD=
APP_DB_PASSWORD=
MINIO_ROOT_PASSWORD=
GRAFANA_ADMIN_PASSWORD=
CREDENTIAL_VAULT_MASTER_KEY=
```

| Variable | How to create it | Notes |
|---|---|---|
| `JWT_SECRET` | `openssl rand -hex 32` | The API refuses to start without it. Changing it signs everyone out. |
| `POSTGRES_PASSWORD` | `openssl rand -hex 32` | Local Docker Postgres only. On Render, the managed database has its own (in `DATABASE_URL`). |
| `APP_DB_PASSWORD` | `openssl rand -hex 32` | Password of the restricted `ceopro_app` database role; the migration runner sets it. |
| `MINIO_ROOT_PASSWORD` | `openssl rand -hex 32` (local MinIO) | On staging/production with Cloudflare R2 it is the R2 **Secret Access Key** instead (section 6). |
| `GRAFANA_ADMIN_PASSWORD` | `openssl rand -hex 32` | Local monitoring stack only (`docker-compose.yml`). |
| `CREDENTIAL_VAULT_MASTER_KEY` | `python -m scripts.vault_key generate` (from `backend/`) | **Must be a Fernet key** (44 characters, base64, ends in `=`). A hex string from `openssl rand -hex` is **rejected** and saving or syncing connectors is refused. Same value on the API and the workers. To replace it, rotate (below) - never just change it. |

**Rotating `CREDENTIAL_VAULT_MASTER_KEY` without losing saved connectors:**
set the new key as `CREDENTIAL_VAULT_MASTER_KEY` and the old one as
`CREDENTIAL_VAULT_PREVIOUS_KEYS` (API and workers), run
`python -m scripts.vault_key check` (every credential opens), then
`python -m scripts.vault_key rewrap`, `check` again, and remove
`CREDENTIAL_VAULT_PREVIOUS_KEYS`. `rewrap` changes nothing if any credential
can't be opened.

Also set, not secret: `CREDENTIAL_VAULT_KMS_BACKEND=local` (or `aws` with
`AWS_KMS_KEY_ID` and AWS credentials, the stronger production option),
`SCRAPER_ACTOR_USER_ID=00000000-0000-0000-0000-000000000000`,
`MINIO_ROOT_USER` and `GRAFANA_ADMIN_USER` (any user name you choose).

## 2. Database, Redis and file storage - REQUIRED, from your host

```
DATABASE_URL=
REDIS_URL=
MINIO_ENDPOINT=
MINIO_ROOT_USER=
MINIO_ROOT_PASSWORD=
```

- `DATABASE_URL` / `REDIS_URL`: copy from Render's managed Postgres / Redis
  (locally the Docker defaults in `.env.example` work).
- File storage (uploads, documents, marketing images), staging/production on
  **Cloudflare R2** (free tier, card on file): create a bucket and an R2 API
  token with read/write on it, then
  `MINIO_ENDPOINT` = `https://<account-id>.r2.cloudflarestorage.com`,
  `MINIO_ROOT_USER` = Access Key ID, `MINIO_ROOT_PASSWORD` = Secret Access Key.
  Without storage everything works except uploads and stored images.

## 3. AI language model - REQUIRED for the assistant, AI analysis and marketing copy

```
GROQ_API_KEY=
```

- **FREE** - console.groq.com -> API Keys. Model: `GROQ_MODEL` (default `openai/gpt-oss-20b`).
- Alternatives (pick one; the first set wins): `PAID_LLM_BASE_URL` +
  `PAID_LLM_API_KEY` (+ `PAID_LLM_MODEL`) for a paid OpenAI-compatible vendor;
  `HUGGINGFACE_LLM_MODEL` (uses `HUGGINGFACE_API_TOKEN`); `LOCAL_LLM_BASE_URL`
  (a llama.cpp server you run).
- **Also needed since the subscription/credits change:** a confirmed price for
  the model, recorded once with
  `python -m scripts.billing_admin set-price ...` (see
  `docs/SUBSCRIPTIONS_AND_CREDITS.md` section 4). Without a price every AI call
  is refused ("not set up") - the key alone is not enough.

## 4. Email - REQUIRED for real users

```
SMTP_HOST=
SMTP_PORT=
SMTP_USERNAME=
SMTP_PASSWORD=
EMAIL_FROM_ADDRESS=
```

- Sign-up codes, password reset, team invitations and alert summaries. Without
  SMTP, codes are only written to the server log.
- Any SMTP provider. FREE: Brevo (300/day), Mailjet, or Gmail with an app password.
- `EMAIL_FROM_ADDRESS` must be a sender your provider has verified.

## 5. Your app's addresses - REQUIRED when deployed (not secret)

```
FRONTEND_BASE_URL=
APP_BASE_URL=
CORS_ALLOWED_ORIGINS=
VITE_API_BASE_URL=
```

- `FRONTEND_BASE_URL`: the frontend's public URL (links in emails).
- `APP_BASE_URL`: the same frontend URL - Stripe sends customers back here after
  checkout and the billing portal.
- `CORS_ALLOWED_ORIGINS`: the **frontend** URL(s) allowed to call the API
  (https, no trailing slash, comma-separated).
- `VITE_API_BASE_URL` (frontend build): the **API**'s public URL.

## 6. Marketing images - FREE, at least one recommended

```
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=
HUGGINGFACE_API_TOKEN=
```

| Variable | Where to get it | Notes |
|---|---|---|
| `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` | dash.cloudflare.com -> AI -> Workers AI -> Use REST API -> create a token (Workers AI permission) | Two separate variables (not `ACCOUNT_ID:TOKEN` in one). |
| `HUGGINGFACE_API_TOKEN` | huggingface.co/settings/tokens -> fine-grained -> "Make calls to Inference Providers" | One token (singular name). Also usable for the AI model (section 3). |

- With neither, images come from the free keyless Pollinations endpoint
  (`MARKETING_IMAGE_KEYLESS=true`, the default). Order and choice:
  `MARKETING_IMAGE_PROVIDERS` (e.g. `cloudflare,huggingface,pollinations`).
- Paid image providers also need a confirmed price (`billing_admin set-price
  --budget ai --provider cloudflare|huggingface --operation image_generation
  --unit image ...`), otherwise they are skipped and the next one is tried.
- **Not used by the code** (remove them from your `.env`, they do nothing):
  `CLOUDFLARE_ACCOUNTS`, `HUGGINGFACE_API_TOKENS` (plural), `GEMINI_API_KEYS`,
  `TOGETHER_API_KEYS`, `HORDE_API_KEYS`, `POLLINATIONS_API_KEYS`.
- Background removal: `MARKETING_BACKGROUND_REMOVAL_PROVIDER=rembg` only on a
  host with about 540 MB free RAM (not Render's free plan). No account.

## 7. Competitor discovery and market data - optional

Free and keyless, always on: OpenStreetMap, Nominatim, Photon, Wikidata,
Overture Maps, GDELT news, Open Food Facts.

```
GOOGLE_PLACES_API_KEY=
GOOGLE_CUSTOM_SEARCH_API_KEY=
GOOGLE_CUSTOM_SEARCH_CX=
BRAVE_SEARCH_API_KEY=
TAVILY_API_KEY=
SEARXNG_INSTANCE_URL=
APIFY_API_TOKEN=
YOUTUBE_API_KEY=
SERPAPI_API_KEY=
```

| Variable | Used for | Where | Cost |
|---|---|---|---|
| `GOOGLE_PLACES_API_KEY` (older name `GOOGLE_MAPS_API_KEY`) | Places discovery, geocoding | console.cloud.google.com -> enable Places API / Geocoding API | **PAID** (billing account required) |
| `GOOGLE_CUSTOM_SEARCH_API_KEY` + `GOOGLE_CUSTOM_SEARCH_CX` | web search | Google Programmable Search | free 100/day, then paid |
| `BRAVE_SEARCH_API_KEY` | web + news search | api.search.brave.com | free tier / paid |
| `TAVILY_API_KEY` | web + news search | app.tavily.com | 1,000 free credits/month |
| `SEARXNG_INSTANCE_URL` | web + news search | a SearXNG server you host | **FREE** (no key) |
| `APIFY_API_TOKEN` (older name `APIFY_TOKEN`) | Google Maps places and reviews | console.apify.com -> Integrations | **PAID** per result |
| `YOUTUBE_API_KEY` | competitors' YouTube comments | Google Cloud -> YouTube Data API v3 | **FREE** (quota) |
| `SERPAPI_API_KEY` | shopping prices | serpapi.com | **PAID** |

Search order: `WEB_SEARCH_PROVIDERS` (the first configured one answers).
**Each paid provider also needs a confirmed price** recorded with
`billing_admin set-price --budget data ...`, or its calls are refused.
Price-feed collectors (ScrapeCreators, Amazon PA-API, Digi-Key, Mouser) take
their credentials from each company's saved connectors, not from environment
variables (their names in `scripts/live_credential_smoke_tests.py` are only for
that smoke test).

## 8. Payments - optional (needed to charge for plans)

```
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRODUCT_ID=
```

- **PAID/regulated**: a Stripe account with business verification.
- `STRIPE_SECRET_KEY`: dashboard.stripe.com -> Developers -> API keys (use
  `sk_test_...` until you go live).
- `STRIPE_WEBHOOK_SECRET`: Developers -> Webhooks -> add endpoint
  `<API URL>/billing/webhook` -> signing secret `whsec_...`.
- `STRIPE_PRODUCT_ID`: optional, only for `scripts/stripe_sync_catalog.py`.
- `STRIPE_AUTOMATIC_TAX=true` only after Stripe Tax is set up.
- Without them, plans and usage still show; checkout says payments aren't on.

## 9. Monitoring - optional

```
SENTRY_DSN=
VITE_SENTRY_DSN=
ALERT_WEBHOOK_URL=
```

- `SENTRY_DSN` (API and workers) / `VITE_SENTRY_DSN` (frontend build): sentry.io
  -> project -> Client Keys. FREE developer tier.
- `ALERT_WEBHOOK_URL`: a Slack/Discord incoming webhook for infrastructure alerts.

## 10. Settings that must have these values (not secret)

```
UNASSIGNED_PLAN_ACCESS=none
BILLING_MAINTENANCE_ENABLED=true
REQUIRE_EMAIL_VERIFICATION=auto
```

- `UNASSIGNED_PLAN_ACCESS=none`: a company without a plan has no access. Use
  `default` only for a single-company install.
- Optional frontend: `VITE_SUPPORT_EMAIL` (Custom plan "Contact sales" button),
  `VITE_SPLINE_HERO_SCENE` (landing-page 3D scene).

---------------------------------------------------------------------------

## Checking an environment

`./keel check` (or `python -m scripts.check_config --db` from `backend/`)
compares the loaded environment with this file: missing required settings,
wrong formats (vault key, addresses, CORS), half-set integrations, names the
code ignores, and paid providers configured without a recorded price. It
prints setting names and problems only, never values. The API logs the same
findings at start-up.

## Minimum to go live

1. Section 1 - six values you generate (Fernet format for the vault key).
2. Section 2 - database, Redis, file storage from your host.
3. Section 3 - `GROQ_API_KEY` **and** its confirmed price (`billing_admin set-price`).
4. Section 4 - SMTP.
5. Section 5 - your public URLs.
6. Section 10 - the fixed settings.

Everything else is optional; add a confirmed price for each paid provider you turn on.
