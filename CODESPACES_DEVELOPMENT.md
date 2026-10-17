# KEEL - GitHub Codespaces Development Environment

This makes GitHub Codespaces the primary place to **develop and test**
KEEL - not a replacement for Render staging (`STAGING_DEPLOYMENT.md`),
which stays the always-on, real-HTTPS-URL environment for showing the app
to someone without a running Codespace. Codespaces solves a different
problem: Render's free tier has a hard 512MB memory ceiling that this
repo's own RAG/ML dependencies (`torch`, `transformers`,
`sentence-transformers`, `faiss-cpu`) can exceed on a real request (see
`STAGING_DEPLOYMENT.md`'s "~780MB RSS" measurement) - a Codespace gives you
real headroom to develop and test the exact same code without fighting
that ceiling.

**Short version:** create the Codespace, wait for setup to finish, run
`./keel start` in a terminal and open the forwarded port 5173. API keys
such as `GROQ_API_KEY` come from the repository's Codespaces secrets
(docs/SECRETS.md), not from a file. To prove the assistant works end to end,
run `./keel rag-check` in a second terminal. The rest of this page explains
what happens underneath.

Nothing here touches Render, Neon, or production. This is a completely
separate, local, throwaway environment - its own Postgres, its own Redis,
its own MinIO, all running inside the Codespace's container.

---

## What this reuses vs. adds

**Reused unmodified**: `backend/docker-compose.yml` (Postgres+pgvector,
Redis, MinIO, the `migrate` one-shot job), `backend/scripts/
apply_migrations.py`, `backend/.env.example` / `frontend/.env.example`,
`backend/Dockerfile.ai`'s exact dependency set (`src/ai/requirements.txt`
installed directly, not rebuilt as an image - see below). Nothing in this
list was changed by this PR.

**Added**: `.devcontainer/devcontainer.json`, `.devcontainer/setup.sh`
(runs once, on Codespace creation), `.devcontainer/start-services.sh`
(runs on every start), `.devcontainer/env_utils.sh` (a small shared
helper), and this document.

---

## Quickstart

```text
Open Codespace
  -> postCreateCommand (setup.sh) runs automatically: installs backend
     Python deps into backend/.venv, installs frontend npm deps, creates
     backend/.env + frontend/.env from the repo's own .env.example files
  -> postStartCommand (start-services.sh) runs automatically: starts
     Postgres+pgvector/Redis/MinIO via docker compose, runs migrations,
     comments out empty backend/.env lines that a Codespaces secret
     provides (e.g. GROQ_API_KEY=), records the assistant model's price in
     this Codespace's own database if it's missing (AI calls are refused
     without one - docs/SUBSCRIPTIONS_AND_CREDITS.md section 4), sets
     CORS_ALLOWED_ORIGINS to your forwarded 5173 URL and VITE_API_BASE_URL
     to /api (the frontend dev server forwards /api to the backend)
Start backend  (Terminal 1): cd backend && source .venv/bin/activate
                              set -a && source .env && set +a
                              uvicorn src.ai.main:app --reload --host 0.0.0.0 --port 8000
Start frontend (Terminal 2): cd frontend && npm run dev -- --host 0.0.0.0
Open the forwarded 5173 URL (Ports tab) in a browser
  -> Use KEEL as a real user: sign up, log in, dashboard, products, etc.
```

The backend/frontend are deliberately **not** auto-started by
`postStartCommand` - they're long-running dev processes you want in their
own visible terminal (so you see logs, and can `--reload`/restart freely
without touching the Codespace lifecycle). Infra (Postgres/Redis/MinIO)
and migrations *are* automatic, since there's no reason to run those by
hand every time.

API credentials are not part of setup: a repository admin adds them once as
**Codespaces secrets** (Settings → Secrets and variables → Codespaces), and
every Codespace created afterwards receives them as environment variables -
restart a running Codespace to pick up a new one. Codespaces secrets are
separate from GitHub **Actions** secrets: CI (`rag-runtime-check.yml`) reads
`GROQ_API_KEY` from Actions secrets, a Codespace only from Codespaces secrets.
`start-services.sh` comments out the matching empty lines in `backend/.env`,
so both `./keel start` and `set -a && source .env` keep the secret's value. No
Hugging Face token is needed: the embedding and re-ranking models are public
(`HUGGINGFACE_API_TOKEN` is only for Hugging Face image or chat models). Without
`GROQ_API_KEY`, the assistant still answers, listing the sources it found
without an AI-written summary. `./keel status` shows which provider is
active and whether its credential is available; `./keel llm-check` checks the
key, the model and its recorded price. Full list and permissions: docs/SECRETS.md.

**Prove the assistant end to end:** with `./keel start` running, run
`./keel rag-check` in a second terminal. Through the same `/api` path the
browser uses, it creates a test company, uploads four PDFs, checks every
chunk got an embedding, asks Arabic questions about the English documents,
expects AI-written answers citing the right document, asks a company-data
question, and checks a second company never sees the first one's documents.
It ends with `PASS` or the list of what failed. The first run downloads the
embedding models (a few minutes). Groq's free tier allows 8,000 tokens a
minute, so the run waits out its rate limit between questions.

---

## Start testing KEEL as a customer

Your Codespace has its own empty database - nobody else's companies, no
demo data - so you start exactly like a new customer.

1. In the Codespace terminal: `./keel start` (starts the database, backend
   and frontend; the first run after creating the Codespace also applies
   database migrations). AI-written assistant answers need the
   `GROQ_API_KEY` Codespaces secret (docs/SECRETS.md).
2. Open the **Ports** tab, find port **5173 (KEEL Frontend)** and open its
   forwarded address in your browser. It can stay Private; port 8000 never
   needs to be opened (the frontend reaches the backend through /api).
3. Click **Sign up** and create your account with your own email and a
   password you choose (8+ characters with an upper- and lower-case letter,
   a number and a symbol). You type it only into KEEL - never share it.
   No email confirmation is needed until an email service is configured.
4. Complete the four setup steps (business type, location, a few products,
   market scan), then use KEEL: upload sales in **Data & Documents**
   (templates are on that page), then open the Command Center, Products,
   Demand, Reports, Competitors and the Assistant.

Forgot your password? Email isn't configured yet, so use the terminal
command in the next section instead of "Forgot password".

What was verified on this branch (local run of the same code, see the
commit log): sign-up, the four setup steps, sales upload, Command Center,
English and Arabic assistant answers from your own sales, sign-out (the
app returns to sign-in and protected pages redirect there), signing in
again with data intact, data surviving a backend restart, another company
seeing none of your data (direct links to your records return "not
found"), and all main screens loading without errors in English, Arabic
(mobile) and dark mode. Not verified here: competitor discovery uses
the free public OpenStreetMap service by default, which this test
environment cannot reach - it should work from your Codespace, but treat it
as untested; web-search discovery needs a search key. Not working without
extra setup: AI marketing images (no image provider configured) and email
delivery.

## Setting your own password

Until an email service is configured (`SMTP_*` in `backend/.env`), password
reset and email-confirmation codes can't be delivered. Set your password from
the Codespace terminal instead - you type it at a hidden prompt; it is never
printed, logged or stored in Git:

```bash
cd backend && set -a && . ./.env && set +a
python -m scripts.set_password --email you@example.com --mark-verified
```

(`--mark-verified` confirms the address; use it only for your own email.)

## Services running by default

| Service | Why it's default |
|---|---|
| PostgreSQL + pgvector | The app's only database - nothing works without it |
| Redis | Session/cache/stream backend several routes depend on |
| MinIO | Object storage for uploads (`/extraction/upload`, marketing images) |
| `migrate` (one-shot) | Applies `Final_schema.sql` + all migrations |
| Backend (`uvicorn`, host process) | The real FastAPI app, run directly for fast `--reload` iteration |
| Frontend (`vite`, host process) | The real React app, run directly for HMR |

## Optional services (not started automatically)

Per the "do not automatically start unnecessary heavy services"
requirement, these stay available but require an explicit command:

```bash
# The 5 market-scraper background workers (competitor discovery/scraping
# pipeline) - Render free can't run these at all (no free Background
# Worker tier); a Codespace can, if you specifically want to test that
# pipeline. Needs real scraping/API credentials to do anything useful.
cd backend && docker compose up -d market-scraper market-analysis-worker \
  market-discovery-worker market-connector-worker market-maintenance

# Genuinely free web-search fallback for the same discovery pipeline
# (src/market_scraper/searxng_discovery.py) - self-hosted SearXNG, no API
# key, used automatically by market-discovery-worker once both are up
# (its SEARXNG_INSTANCE_URL already defaults to this service's own
# hostname - no .env edit needed). Google Custom Search/Places still take
# priority when GOOGLE_CUSTOM_SEARCH_API_KEY/GOOGLE_PLACES_API_KEY are set;
# this is what actually runs when they aren't.
cd backend && docker compose up -d searxng market-discovery-worker

# The observability stack (Prometheus/Loki/Promtail/Grafana) - useful if
# you're specifically debugging metrics/logs, unnecessary for ordinary
# feature development.
cd backend && docker compose up -d prometheus loki promtail grafana redis-exporter

# A fully local, zero-cost LLM (llama.cpp) instead of Groq - see
# docker-compose.yml's own comment on the llm-local service and
# scripts/download_local_llm_model.py for the one-time model download it
# needs first. Point backend/.env's LOCAL_LLM_BASE_URL at
# http://localhost:8090/v1/chat/completions to actually use it once running.
cd backend && docker compose --profile local-llm up -d llm-local
```

---

## How Codespaces URLs are handled (no hardcoding)

`httpClient.js` authenticates with a `Bearer <JWT>` header, not a cookie
- there's no SameSite/cookie-domain problem to solve for cross-origin
forwarded-port testing, which is the usual Codespaces auth headache. What
actually needs to be correct is CORS + the frontend's API base URL, and
both are set dynamically by `start-services.sh` on every start (not
hardcoded, since a Codespace's name - and therefore its forwarded URL -
differs per Codespace):

- `backend/.env`'s `CORS_ALLOWED_ORIGINS` -> your Codespace's forwarded
  5173 URL (`https://$CODESPACE_NAME-5173.app.github.dev`)
- `frontend/.env`'s `VITE_API_BASE_URL` -> `/api`: the browser calls the
  API on the frontend's own address, and the Vite dev server forwards it to
  the backend on `localhost:8000` (`frontend/vite.config.js`), which also
  allows the `*.app.github.dev` host name (Vite otherwise answers "Blocked
  request. This host is not allowed").

**Port visibility**: only 5173 is used from the browser. Leave it
**Private** and open it from a browser signed into the same GitHub account
(works from another device too). Port 8000 can stay private - nothing in
the browser calls it directly.

No authentication system was changed - this only ever adjusts which
origins are allowed to call the same existing JWT-header-based API.

---

## Machine size

**Recommended: 4-core / 16GB.** This is what's needed to run the full
default stack (Postgres+pgvector, Redis, MinIO, the backend with
torch/transformers/faiss-cpu loaded, and the frontend dev server)
comfortably at once, with headroom - specifically the headroom Render's
512MB free tier doesn't have (see `STAGING_DEPLOYMENT.md`'s measured
~780MB RSS for the RAG embedding import alone).

**Smaller machines (2-core/8GB)**: usable for backend+frontend+Postgres+
Redis, but skip MinIO and don't load the RAG/ML-heavy endpoints
simultaneously with everything else running - it'll be tight. Not
recommended as your only option if you're doing RAG/ML work specifically,
which is the whole reason this document exists.

`.devcontainer/devcontainer.json`'s `hostRequirements` states 4-core/16GB
as a suggestion GitHub's Codespace-creation UI surfaces - it is not a
hard minimum enforced by GitHub, you can still pick a smaller machine.

---

## $0 safety - read this before creating a Codespace

GitHub Codespaces is **not unconditionally free**. It includes a monthly
free allowance (core-hours, consumed faster on bigger machines, plus a
separate storage allowance) that varies by GitHub plan - check your
actual current allowance at **Settings -> Billing -> Codespaces** before
relying on any specific number, since GitHub has changed these figures
before and this document won't stay current on its own.

**The one action that actually guarantees $0**: set your Codespaces
**spending limit to $0** (organization or personal account billing
settings). At $0, GitHub does not silently bill you once the free
allowance runs out - it simply refuses to start new Codespaces (and
auto-stops running ones) until the next billing cycle or until you raise
the limit yourself. This is not the default setting - you need to set it
explicitly.

**Persistence**: a stopped Codespace's filesystem (installed deps,
Postgres data volume, everything) persists across stop/start. GitHub
auto-deletes a Codespace after a period of inactivity (default 30 days,
configurable shorter, not longer) - unlike Render's free web service,
which never gets deleted, only cold-starts. Don't treat a Codespace as
permanent storage for anything you haven't pushed to a branch.

**No paid services, no credit card required by this setup**: default
local Postgres/pgvector/Redis/MinIO, no Cloudflare R2, no paid LLM
provider (Groq's free tier or the local `llm-local` profile only). The
only thing you might add yourself that touches an external paid-capable
provider is `GROQ_API_KEY` (free tier) - same as Render staging, not a
new requirement.

---

## What was actually validated, and what wasn't

Honestly, from a non-Codespaces sandbox that does not have a running
Docker daemon available:

**Validated**:
- `.devcontainer/devcontainer.json` is syntactically valid JSONC.
- All three new shell scripts pass `bash -n` (syntax-checked).
- `backend/scripts/apply_migrations.py` and the full backend pytest
  suite (including live-DB integration tests) run successfully against a
  real local Postgres instance - see the PR body / final report for the
  exact numbers. This proves the migration/schema/backend-logic path
  this setup depends on is real and correct.
- Frontend test suite and production build (`npm run build`) both pass.

**NOT validated from this sandbox** (report from a real Codespace before
fully trusting this document):
- Actually opening a GitHub Codespace from this configuration end-to-end
  (`devcontainer.json`'s features/lifecycle hooks executing as GitHub
  Codespaces itself runs them - this sandbox has the `docker` CLI but no
  daemon, so `docker compose up` could not be executed here).
- Real port forwarding, the actual forwarded HTTPS URL shape, and
  browser access from another device.
- A live end-to-end signup/login/dashboard walkthrough through the
  forwarded frontend URL.

If you open a real Codespace from this branch and hit anything that
doesn't match this document, that's the gap to report back - this was
written from careful reading of the existing docker-compose.yml/
Dockerfile.ai/env files and Codespaces' documented port-forwarding/env-var
behavior, not from having run it inside an actual Codespace.
