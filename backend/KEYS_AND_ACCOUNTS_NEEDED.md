# Keys, tokens and accounts needed - fill-in checklist

Every value below is **blank on purpose**. Never commit real values (git history
is permanent). Put them in your local `backend/.env` (git-ignored) and in
Render -> your service -> **Environment** for the deployed app.

Legend: **FREE** = no payment needed - **PAID** = needs a paid plan or card -
**YOU GENERATE** = no account, you create the value yourself.

> Completeness note: this list was written from the variables visible in
> `backend/.env.example` (first ~290 lines), `render.yaml` and the code. If
> `.env.example` has a variable that is not listed here, it is optional tuning
> unless it ends in `_KEY`, `_TOKEN`, `_SECRET` or `_PASSWORD` - check those.

---------------------------------------------------------------------------

## 1. Secrets you generate yourself (no account) - REQUIRED

Generate each with `openssl rand -hex 32` in a terminal, one per variable.

```
JWT_SECRET=8a72d8377cdd7d8d84d2a69482c835ac3d399de64db165f3f1b1589ce5563077
POSTGRES_PASSWORD=538c581df4ed75c51a254d3d98547740c93bc2b36837a5c7fb896f8fc5a694a4
APP_DB_PASSWORD=3846d062a53a0fae9247f5b27060cd8bc9500f340fd76ec2d15abb71bb3e6d8e
MINIO_ROOT_PASSWORD=5D11E19FE268D0E38BAC176E79289C8B967C12BA77CADA2F60E6AB9473F18C11
GRAFANA_ADMIN_PASSWORD=6687920e6b05cc29b7cabba20c1905eb78b7cbd524cefa960d471e6f15225f11
CREDENTIAL_VAULT_MASTER_KEY=d9783b1a328f44b2a6d50d4324b31ed0b6372ca3e7e39cecc55675d35b978f9f
```

- `JWT_SECRET`: the app refuses to start without it.
- `CREDENTIAL_VAULT_MASTER_KEY`: encrypts the database-connector credentials
  tenants save. **Its required format is defined in the code and I could not
  confirm it** - read the comment above where it is used before generating, and
  never change it after tenants have saved connectors (they become unreadable).
- On Render, managed Postgres/Redis give you their own connection strings;
  use those for `DATABASE_URL` / `REDIS_URL` instead of the local defaults.

## 2. Marketing images (this feature) - all FREE

At least one keyed account is strongly recommended; with none, users get the
local "designed" poster (works, but is not AI-generated) or a slow AI Horde image.
More accounts = more free AI images per day (comma-separate several).

```
CLOUDFLARE_ACCOUNTS=e20eeea75975181122485dfa91bf1174
HUGGINGFACE_API_TOKENS=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
GEMINI_API_KEYS=AIzaSyC4eNPTtu8sU6eo9g8kcQWOXJ8TmCmyqAI
TOGETHER_API_KEYS=key_Cg7vyeHCF8x1ZvySk6EnA
HORDE_API_KEYS=9AdtPPfeSBer8mRWQV9osA
POLLINATIONS_API_KEYS=sk_BQ3nPBNVMJYQvspIQLT6SFjCTAnoK8YV
```

| Variable | Format | Where to get it | Notes |
|---|---|---|---|
| `CLOUDFLARE_ACCOUNTS` | `ACCOUNT_ID:TOKEN` (colon, no spaces) | dash.cloudflare.com -> AI -> Workers AI -> Use REST API -> Create a Workers AI API Token | **Best first choice.** Token permission: Account -> Workers AI -> Read (Edit is fine). Free daily allowance. |
| `HUGGINGFACE_API_TOKENS` | `hf_...` | huggingface.co/settings/tokens -> Fine-grained -> tick "Make calls to Inference Providers" | Free monthly credit is small (a few dozen images). |
| `GEMINI_API_KEYS` | `AIza...` | aistudio.google.com/apikey | Free tier with limits; the model name may change (`GEMINI_IMAGE_MODEL`). |
| `TOGETHER_API_KEYS` | key | api.together.ai | Uses the free FLUX.1-schnell-Free model; availability not verified. |
| `HORDE_API_KEYS` | key | aihorde.net/register | Optional. Without it the anonymous key still works but queues for minutes. |
| `POLLINATIONS_API_KEYS` | key | enter.pollinations.ai | Optional. Never used without a key (keyless images carry a visible watermark). |

**About "how many models":** free quotas are per *account*, not per model - extra
models from the same account do not add images; extra accounts do. Models used:
Cloudflare 4 (FLUX.1-schnell, SDXL-Lightning, SDXL-base, DreamShaper-8), Hugging
Face 2 (FLUX.1-schnell, SDXL-base), Gemini 1, Together 1, and AI Horde (a network
of dozens of community models, no per-model cap but a slow queue). To raise the
free volume, add more accounts (comma-separated), e.g. a second Cloudflare account.

Rules: do not put any of these in a committed file; roll (regenerate) a token
immediately if it is ever pasted in chat, a screenshot or an issue.

## 3. Marketing: background removal - FREE, nothing to sign up for

```
MARKETING_BACKGROUND_REMOVAL_PROVIDER=
```

Set to `rembg` only on a host with real RAM headroom (it needs about 540MB;
Render's free plan has 512MB and would kill the service - see
`MARKETING_AI_CAPABILITIES.md` section 1a).

## 4. Chat / copy writing (LLM) - REQUIRED for chat and marketing copy

Marketing copy (headlines, captions, hashtags) and the business chat both use
the language model. Pick ONE option.

```
GROQ_API_KEY=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
```

- **FREE** - console.groq.com -> API Keys (free tier with rate limits).
- Alternatives: `LOCAL_LLM_BASE_URL` (a llama.cpp server you run - free but slow)
  or `PAID_LLM_BASE_URL` + `PAID_LLM_API_KEY` (+ `PAID_LLM_MODEL`) for a paid
  OpenAI-compatible vendor. A set `PAID_LLM_*` wins over the others.

## 5. Email (password reset, verification, team invites, alert digests)

Without SMTP the app still runs, but no email is sent (reset codes and invites
never arrive), so **required for real users**.

```
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USERNAME=be9c22001@smtp-brevo.com
SMTP_PASSWORD=xsmtpsib-a915711c21fe2c03fcd62488eb921803079a4b1e372c637cba80b1b9be9c3e1f-dpSsGcwdCWNxAKF0
EMAIL_FROM_ADDRESS=huda.hasouneh@gmail.com
FRONTEND_BASE_URL=https://fuzzy-yodel-p79gw575pxg6cg7x-5173.app.github.dev
CORS_ALLOWED_ORIGINS=https://fuzzy-yodel-p79gw575pxg6cg7x-8000.app.github.dev
```

- Any SMTP provider works. FREE options with a small daily limit: Brevo
  (300/day), Mailjet, or Gmail with an **app password** (Google Account ->
  Security -> 2-Step Verification -> App passwords).
- `EMAIL_FROM_ADDRESS` must be an address your provider has verified.
- `FRONTEND_BASE_URL` and `CORS_ALLOWED_ORIGINS`: your real deployed frontend
  URL (https, no trailing slash). The localhost defaults will not work online.

## 6. Storage and infrastructure - provided by your host

```
MINIO_ENDPOINT=http://minio:9000
MINIO_ROOT_USER=minio_admin
DATABASE_URL=postgresql://ceopro_admin:538c581df4ed75c51a254d3d98547740c93bc2b36837a5c7fb896f8fc5a694a4@postgres:5432/ceopro_platform
REDIS_URL=redis://redis:6379/0
```

Production needs an S3-compatible bucket store (MinIO, or equivalent) and managed
Postgres + Redis. Copy the connection details from your hosting dashboard.

## 7. Optional integrations (features degrade gracefully when blank)

```
GOOGLE_PLACES_API_KEY=
GOOGLE_CUSTOM_SEARCH_API_KEY=
GOOGLE_CUSTOM_SEARCH_CX=
ALERT_WEBHOOK_URL=
```

- Google keys: console.cloud.google.com -> enable "Places API" / "Custom Search API".
  **Google requires a billing account on file** even for the free monthly credit,
  so treat these as PAID/optional. They power competitor discovery.
- Competitor discovery via Apify (the project has an Apify integration) needs an
  Apify token; I could not confirm the variable name - look in `.env.example`.
- `ALERT_WEBHOOK_URL`: a Slack/Discord/other incoming-webhook URL for infra alerts.

## 8. Billing (only if you charge for plans)

`render.yaml` declares `STRIPE_WEBHOOK_SECRET`; billing also needs Stripe's API
secret key. **PAID/regulated** - Stripe account with business verification.
Leave blank to run without billing. Check `.env.example` for the exact names.

---------------------------------------------------------------------------

## Minimum to go live with the marketing feature working

1. Section 1 (all six generated secrets).
2. `CLOUDFLARE_ACCOUNTS` (section 2) - add `HUGGINGFACE_API_TOKENS` and
   `GEMINI_API_KEYS` for more free daily images.
3. `GROQ_API_KEY` (section 4).
4. SMTP + `FRONTEND_BASE_URL` + `CORS_ALLOWED_ORIGINS` (section 5).
5. Hosting-provided Postgres / Redis / storage (section 6).

Everything else is optional.
