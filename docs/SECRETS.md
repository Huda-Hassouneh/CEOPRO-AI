# KEEL secrets: names, purposes and where each is set

Names only. No value of any secret belongs in this repository: not in
`.env.example`, `backend/.env`, source code, documentation, commit messages,
logs, or an encrypted file committed to Git. Each environment keeps its own
values in its own secret settings, and **none of them is shared
automatically**: a Codespaces secret is not visible to GitHub Actions, and
neither reaches Render.

| Environment | Where its secrets live |
|---|---|
| Codespaces (development) | GitHub repository → **Settings → Secrets and variables → Codespaces → New repository secret** |
| GitHub Actions (CI) | GitHub repository → **Settings → Secrets and variables → Actions → Secrets → New repository secret** (non-secret settings such as a model name: the **Variables** tab) |
| Render staging (`keel-ai-staging`) | Render dashboard → the service → **Environment** (the `sync: false` keys in `render.yaml`) |

Only a repository admin can add repository secrets. Each person creating a
key should create it for KEEL on the project's own account, not reuse a
personal key.

## API credentials

The application reads each one from an environment variable and never
prints it. Where a credential is missing, the feature that needs it says
it isn't configured instead of failing.

| Name | Needed for | Required? | Least privilege | Codespaces | Actions | Render |
|---|---|---|---|---|---|---|
| `GROQ_API_KEY` | AI-written assistant answers (the default LLM provider). Without it, the assistant lists the cited sources it found, unsummarised | Required for AI answers | A normal Groq API key (Groq has no narrower scope); free tier | yes | yes - CI then checks answers are written by the LLM | yes |
| `HUGGINGFACE_API_TOKEN` | Hugging Face Inference Providers for assistant answers, **only when `HUGGINGFACE_LLM_MODEL` is set** (see below); marketing images with `MARKETING_IMAGE_PROVIDER=huggingface` | Optional | Fine-grained token with only **"Make calls to Inference Providers"** ticked, no repository access | yes, if used | yes, if used | only if used |
| `TAVILY_API_KEY` | Public web research in assistant answers (preferred free provider: 1,000 credits/month, no card) | Optional | Default key | optional | no | optional |
| `BRAVE_SEARCH_API_KEY`, `SERPAPI_API_KEY`, `GOOGLE_CUSTOM_SEARCH_API_KEY` + `GOOGLE_CUSTOM_SEARCH_CX` | Alternative web-research providers | Optional | Search-only keys | optional | no | optional |
| `GOOGLE_PLACES_API_KEY` | Competitor discovery via Google Places | Optional | Restricted to the Places API | optional | no | optional |
| `APIFY_API_TOKEN` | Competitor discovery via Apify's Google Maps actor, and Google reviews read beyond the Places API's five (with likes and owner replies). **Each run is billed to the Apify account.** `APIFY_TOKEN`, the older name, still works | Optional | A scoped Apify API token | only if needed | no | optional (both `keel-ai-staging` and `keel-workers-staging`) |
| `YOUTUBE_API_KEY` | Public YouTube comments, with likes, on videos naming a competitor | Optional | An API key restricted to the YouTube Data API v3 (free daily quota) | optional | no | optional (`keel-ai-staging`, `keel-workers-staging`) |
| `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` | Marketing images via Cloudflare Workers AI | Optional | Token with Workers AI access only | optional | no | optional |
| `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD` | Sending email (verification, digests). Without them, emails are logged as not sent | Optional in development | An SMTP credential for the sending address only | no | no | yes, for real email |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Billing | Production only | A restricted Stripe key | no | no | yes, once billing is live |
| `SENTRY_DSN` (frontend: `VITE_SENTRY_DSN`) | Error reporting | Optional | A DSN (write-only) | no | no | optional |

Non-secret settings that go with these are ordinary variables, not
secrets: `GROQ_MODEL`, `HUGGINGFACE_LLM_MODEL`, `MARKETING_IMAGE_PROVIDER`,
`RAG_EMBEDDING_BACKEND`. In Actions, `HUGGINGFACE_LLM_MODEL` is a repository
**variable**.

## Generated per environment, never shared

These are infrastructure values, not shared API credentials. Don't add them
as Codespaces secrets.

- **Codespaces:** `.devcontainer/setup.sh` generates `JWT_SECRET` and
  `CREDENTIAL_VAULT_MASTER_KEY` once, inside that Codespace's own
  `backend/.env` (git-ignored). The local Postgres, Redis and MinIO
  passwords are throwaway Docker defaults.
- **CI:** each workflow uses throwaway values for its own short-lived
  services.
- **Render:** `render.yaml` generates `JWT_SECRET`; `DATABASE_URL`,
  `APP_DB_PASSWORD`, the MinIO/R2 keys and `CREDENTIAL_VAULT_MASTER_KEY` are
  set once in the service's Environment (see `STAGING_DEPLOYMENT.md`).

## Codespaces: setting up and checking

1. A repository admin adds each needed key under **Settings → Secrets and
   variables → Codespaces → New repository secret**, using the exact name
   from the table. A repository-level Codespaces secret is available in
   every Codespace created from this repository by anyone allowed to create
   one.
2. Secrets are read when a Codespace starts. After adding one, stop and
   restart the Codespace (or rebuild it).
3. `backend/.env` keeps every secret name empty. `./keel` loads that file
   but keeps the environment's value for any name the file leaves empty, so
   the Codespaces secret is what the API sees. A value typed into
   `backend/.env` still wins, and stays on that machine only.
4. Check without revealing anything:
   - `./keel status` names the assistant's active provider and whether its
     credential is available.
   - `./keel llm-check` sends one real request with a fixed prompt and no
     company data; it prints PASS only when the model answers.
   - `python -m scripts.rag_e2e_check ...` (see that script) tests the
     assistant end to end. With a provider configured, an answer that falls
     back to evidence mode fails the check.

## Assistant LLM providers

Selection order in `src/ai/rag/llm_client.py` (`active_provider()`):

1. `PAID_LLM_BASE_URL` (+ `PAID_LLM_API_KEY`, `PAID_LLM_MODEL`): any
   OpenAI-compatible vendor.
2. `HUGGINGFACE_LLM_MODEL` (+ `HUGGINGFACE_API_TOKEN`): Hugging Face
   Inference Providers, through `https://router.huggingface.co/v1/chat/completions`.
   The model id may pin the provider behind the router, for example
   `openai/gpt-oss-20b:groq`.
3. `LOCAL_LLM_BASE_URL`: a llama.cpp server on infrastructure you run (no
   external call).
4. Groq with `GROQ_API_KEY`: the default.

The Hugging Face token alone never changes the provider. Choosing
`HUGGINGFACE_LLM_MODEL` is the opt-in, and a model without its token is
reported as not configured, never silently sent to Groq.

**Data:** with Groq, Hugging Face or a paid vendor, each question and the
company passages retrieved for it are sent to that provider (with Hugging
Face, also to the third-party provider behind the router). Only
`LOCAL_LLM_BASE_URL`, or no LLM at all (evidence mode), keeps them inside
your own infrastructure.

**Cost:** free Hugging Face accounts get a small monthly Inference
Providers credit. When it runs out, requests are refused unless billing is
set up on that account, and the assistant then answers in evidence mode.

## Verification status (2026-10-17)
- **Groq:** a real request through `scripts/llm_provider_check.py`
  succeeded ("ready", 0.7 s) in a development sandbox, with a key provided
  by that sandbox's own environment. The GitHub Actions secret
  `GROQ_API_KEY` is not set yet, so CI answers in evidence mode.
- **Hugging Face Inference Providers:** implemented and unit-tested. **Not
  yet verified with a real request:** no `HUGGINGFACE_API_TOKEN` was
  available, and the development sandbox's network policy blocks
  `router.huggingface.co`. After the Actions secret is added, the "LLM
  providers - one real request each" step of `rag-runtime-check.yml`
  makes that request.
- **Codespaces secrets:** none can be listed or added from outside
  GitHub's settings. Whoever adds them can confirm with `./keel status` and
  `./keel llm-check`.
