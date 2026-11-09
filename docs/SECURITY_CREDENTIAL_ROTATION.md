# Credential rotation runbook

This document lists setting **names only, never values**. Two incidents are covered:

1. **2026-11-09 (OPEN): production secrets stored as plaintext variables in the owner's agent cloud
   environments.** Ordered runbook below.
2. **2026-10-19 (OPEN): credentials committed to public Git history.** Inventory at the end of this file.

## 2026-11-09: production secrets in agent cloud environments

`JWT_SECRET`, `DATABASE_URL` (contains the Neon owner password), `APP_DB_PASSWORD` (`ceopro_app`), `REDIS_URL`
(Upstash password), `BREVO_API_KEY` / the Brevo SMTP key, `GROQ_API_KEY` (and `POSTGRES_PASSWORD`, per
`docs/TASK_REGISTER.md`) were plain environment variables in the agent environments `ceopro-ai` and `Default`,
readable by every process an agent started. They must be treated as exposed. Already done: removed from `ceopro-ai`.
Still open: `Default` - **only the owner** can remove them (claude.ai -> Settings -> environments -> Default ->
delete each variable). Do that first; rotating while a copy still sits there re-exposes the new values the moment
anyone copies them back.

### Rules for every step

- **Who acts.** Provider dashboards (Neon, Upstash, Brevo, Groq, GitHub): the **owner**. Render `ceopro-ai-new`
  (API) and any other KEEL service that holds the same variable: the **owner in the Render dashboard**, or
  **Session 1** (the only deployer) triggering/watching the deploy through the Render API. **New values are
  typed only into the Render dashboard (Environment page) or a provider's own form** - never into chat, an agent
  environment, a commit, a log, a ticket, or a Render API call made by an agent. Agents handle variable *names*
  and deploy ids only.
- **Only KEEL services.** The Render account also holds unrelated services (360-Radar). Nobody lists, reads or
  changes them during this work; Session 1 works from the KEEL service ids it already knows.
- **One secret per deploy**, verify, then the next. Each step below says what keeps customers working, how to
  verify, and how to roll back. Keep the old value available (in the provider, not in chat) until the step is
  verified, except where the provider's reset destroys it (Neon, Upstash: see their rollback).
- **Inventory first (step 0).** Session 1 records, by name, which KEEL Render services (API, processor, workers,
  staging) and which GitHub Actions secrets hold each variable. Every step updates *all* of them in the same
  window. Known extra copies: `GROQ_API_KEY` is also a GitHub Actions secret (`live-llm-verification.yml`,
  `rag-runtime-check.yml`); `SCRAPER_DATABASE_URL`, if set, embeds the `ceopro_app` password; the Overture
  on-disk cache is signed with `JWT_SECRET` when `OVERTURE_CACHE_SIGNING_KEY` is unset (rotation only makes
  the cache rebuild once).

### Standard verification (run after every step; Session 2 repeats it read-only)

| Check | Expect |
|---|---|
| `GET https://<api>/health/ready` | 200, `database.ok` and `redis.ok` true |
| Render deploy | the new deploy is `live`, logs show `Applying database schema and migrations...` then the server starting, no `[error]` config-check lines |
| Sign-in | a test account signs in on keelai.net and the dashboard loads; a tab that was **already signed in before the deploy** keeps working (no sign-out) |
| Email | request a password-reset code for a test account: it arrives |
| Assistant | ask the assistant one question: an AI-written answer (not the "sources only" fallback) |
| Billing (read-only) | the Billing page loads for a test tenant; no Stripe action is needed |

### Step 0 - prerequisites (no secret changes)

1. Owner removes the variables from the `Default` agent environment (above).
2. PR `fix/jwt-key-rotation-overlap` (adds `JWT_SECRET_PREVIOUS`) is merged by the owner and **deployed by
   Session 1**; Session 2 verifies the deploy with the table above. Step 1 must not start before this: code
   without it ignores `JWT_SECRET_PREVIOUS` and the rotation would sign everyone out.
3. Session 1 notes the current live deploy id of each KEEL service as the code rollback target, and completes
   the inventory above.
4. Neon: confirm a restore point exists (Neon -> project -> Backup & Restore / branch history; free plan keeps a
   short history window). No data changes in this runbook, but the owner password grants full access.

Steps 2-6 do not depend on the PR and can go first if its merge is delayed.

### Step 1 - `JWT_SECRET` (sessions keep working)

How the overlap works (`backend/src/ai/core/jwt_keys.py`): new tokens are signed **only** with `JWT_SECRET`;
verification tries `JWT_SECRET`, then `JWT_SECRET_PREVIOUS`. `exp` stays required; sign-out revocation, the
password-change cut-off and `credential_version` checks apply to both keys unchanged. The app renews a token
before it expires (`POST /auth/refresh`, re-signed with the new key, keeping the original sign-in time).

1. Owner, Render dashboard -> `ceopro-ai-new` -> Environment: add `JWT_SECRET_PREVIOUS` with **exactly** the
   current `JWT_SECRET` value (reveal and copy inside the dashboard), then replace `JWT_SECRET` with a new value
   (Render's *Generate* button, or `openssl rand -hex 32` on the owner's own machine). Repeat on every other KEEL
   service that holds `JWT_SECRET`. Save; Session 1 deploys and watches it go live.
2. Verify: standard table. Specifically: the tab signed in before the deploy keeps working and, within
   ~10 minutes of activity, renews; a new sign-in works; the logs show one `[warning] JWT_SECRET_PREVIOUS: is
   set ...` line (proves the variable is read) and no `[error] JWT_SECRET...` line.
3. **Remove `JWT_SECRET_PREVIOUS` - step 7.** Every token in use is at most `JWT_EXPIRE_MINUTES` (120 in
   `render.yaml`) old, and renewals since the deploy are signed with the new key, so after
   `JWT_EXPIRE_MINUTES` + 1 hour (3 hours) no valid token depends on the old key. The absolute upper bound is
   `SESSION_MAX_HOURS` (168 h = 7 days). **Recommendation: remove it after 3 hours, not 7 days** - the old
   key is exposed, and while it is accepted anyone holding it can still mint a session for any account.
- Rollback: if sign-ins fail after the deploy, set `JWT_SECRET` back to the old value and
  `JWT_SECRET_PREVIOUS` to the new one (both stay accepted, nobody is signed out), deploy, investigate. If the
  code itself is at fault, Session 1 rolls back to the step-0 deploy id **and** the owner restores
  `JWT_SECRET` to the old value and deletes `JWT_SECRET_PREVIOUS` (old code knows only one key).
- Customer impact: none expected. A tab idle for longer than a token lifetime signs out, exactly as on any day.

### Step 2 - Neon owner password (`DATABASE_URL`, `POSTGRES_PASSWORD`)

`DATABASE_URL` is the migration/owner login: used at every API start (`scripts/apply_migrations.py`) and at
runtime by `db.system_connection()` (verified Stripe events, starting a free trial). Request traffic uses
`ceopro_app` and is not affected. Neon has one password per role and its reset takes effect immediately, so
there is a short window.

1. Pick a quiet time. Owner, Neon console -> project -> Roles -> the owner role -> **Reset password**; copy the
   new password straight into Render: `ceopro-ai-new` -> Environment -> edit `DATABASE_URL` (replace only the
   password part; keep host, database and `?sslmode=require`) and `POSTGRES_PASSWORD` if present, on every KEEL
   service in the inventory. Save; Session 1 deploys at once.
2. Window: from the reset until the new deploy is live (a few minutes). Requests, sign-in and the assistant keep
   working; a Stripe webhook arriving then fails and **Stripe retries it** (handling is idempotent); a trial
   started then fails and the user can retry. No payment is lost.
3. Verify: standard table; deploy logs show the migration runner finished (it connects with the new owner
   password); Stripe Dashboard (test or live, read-only) -> Webhooks shows later deliveries succeeding.
- Rollback: the old password cannot be restored (and must not be). If the deploy fails to connect, the value in
  Render is wrong: reset again in Neon and re-enter it. Code rollback is unaffected.

### Step 3 - `APP_DB_PASSWORD` (`ceopro_app`)

On every start, `scripts/apply_migrations.py` runs `ALTER ROLE ceopro_app WITH PASSWORD` from
`APP_DB_PASSWORD` (as the owner), before the server starts. Can be done in the same deploy as step 2.

1. Owner, Render: replace `APP_DB_PASSWORD` with a new random value (Generate) on every KEEL service that holds
   it, and update `SCRAPER_DATABASE_URL`'s password part if that variable is set. Save; Session 1 deploys.
2. Continuity: the new instance changes the password, then starts. The old instance keeps its already-open pool
   connections (PostgreSQL does not drop them on a password change) until Render switches traffic; only new
   connections it opens in that minute fail. Any other KEEL service using `ceopro_app` must get the new value in
   the same window.
3. Verify: standard table (`/health/ready` checks the database **as `ceopro_app`**).
- Rollback: set `APP_DB_PASSWORD` back to the old value and deploy - the next start re-syncs it. (Only until the
  step is verified; afterwards the old value is exposed and must not return.)
- The same pattern covers `BILLING_SETUP_DB_PASSWORD`, `BILLING_WEBHOOK_DB_PASSWORD`,
  `CREDIT_ACCOUNTING_DB_PASSWORD`, `IMAGE_WORKER_DB_PASSWORD`; rotate them too, since the exposed owner
  password could read or change any role.

### Step 4 - Upstash Redis (`REDIS_URL`)

Redis holds the rate-limit counters, the sign-out cache, queues and caches. When it is unreachable the rate
limiter lets requests through, sign-out checks fall back to the database receipts, and `/billing` refuses
(fails closed) - so keep the window short.

1. Owner, Upstash console -> the database -> **Reset password** (data is kept); copy the new connection string
   (`rediss://...`) straight into Render `REDIS_URL` on every KEEL service. Save; Session 1 deploys at once.
2. Verify: standard table (`redis.ok` true); sign out and back in (the revocation write needs Redis).
- Rollback: the old password is gone; if the deploy cannot connect, the string in Render is wrong - copy it
  again from Upstash.

### Step 5 - Brevo (email)

Brevo allows several keys at once, so this has no window.

1. Owner, Brevo -> SMTP & API: create a **new** SMTP key (the value KEEL uses as `SMTP_PASSWORD`) and, if a
   `BREVO_API_KEY` is configured anywhere, a new API key. Enter it in Render; Session 1 deploys.
2. Verify: the password-reset email arrives; Brevo -> Transactional logs show it sent.
3. Then owner deletes the **old** SMTP key / API key in Brevo.
- Rollback: before deleting the old key, put it back in Render and deploy.

### Step 6 - Groq (`GROQ_API_KEY`)

Several keys can exist at once: no window.

1. Owner, console.groq.com -> API Keys: create a new key; enter it in Render (every KEEL service that holds it)
   and in GitHub -> repository Settings -> Secrets -> Actions -> `GROQ_API_KEY`. Session 1 deploys.
2. Verify: the assistant gives an AI-written answer; Groq console shows usage on the new key.
3. Then owner deletes the old key in Groq.
- Rollback: before deleting the old key, put it back and deploy.

### Step 7 - finish

1. 3 hours after step 1 went live (at most 7 days): owner deletes `JWT_SECRET_PREVIOUS` in Render; Session 1
   deploys; verify: standard table, and the `JWT_SECRET_PREVIOUS` warning line is gone from the logs.
2. Owner confirms no old value remains in any agent environment, `.dev/` file or password manager entry that is
   shared with agents.
3. Session 2 runs the full read-only production verification and records it in `docs/TASK_REGISTER.md`.

---

## 2026-10-19: credentials exposed in public Git history

**Status: OPEN. Not resolved.** Removing the file from the latest commit (done in `4c5536e`) does not remove it
from history: anyone can still read it at commit `128dba2` (merged 2026-10-19) of this public repository, and it
may already be in forks, clones and search-engine caches. Every value in it must be treated as known to the
public. This document lists names only, never values.

Exposed in three places: the repository-root `.env` (commit `128dba2`) and earlier versions of
`backend/KEYS_AND_ACCOUNTS_NEEDED.md` and `.env.example` (2026-10-13 to 2026-10-19; see the system audit). The root
`.env`'s URLs point at Docker service names (`postgres`, `searxng`) and
`localhost`, so it was written for the Docker/local setup. That does not make it harmless: if any of these values
was ever reused on Render (staging or production), in a Codespace secret, or for another account, that place is
exposed too. Whether that happened cannot be checked from the development sandbox.

## Rotate (owner action, in this order)

| # | Name(s) | What it protects | Where to rotate | Notes |
|---|---|---|---|---|
| 1 | `GROQ_API_KEY` | Paid/rate-limited Groq account | console.groq.com → API Keys: **delete** the old key, create a new one, put it in Render's environment (never in chat or Git) | The key reachable from the sandbox already returns 401, which suggests it was revoked; confirm it is deleted. |
| 2 | `CREDENTIAL_VAULT_MASTER_KEY` | Encrypts customers' stored connector credentials (database/API connectors) | Generate a new key; set it as `CREDENTIAL_VAULT_MASTER_KEY` and the old one in `CREDENTIAL_VAULT_PREVIOUS_KEYS`; run `python -m scripts.vault_key rewrap`; then remove the old key | If the exposed key was ever used outside local Docker, also ask affected customers to rotate the connector passwords they stored. |
| 3 | `JWT_SECRET` | Signs every login session | Render environment; generate with `python -c "import secrets;print(secrets.token_hex(32))"` | Rotate without signing anyone out with `JWT_SECRET_PREVIOUS` (step 1 above). Anyone with the old secret can forge a session for any company. |
| 4 | `POSTGRES_PASSWORD`, `DATABASE_URL`, `APP_DB_PASSWORD`, `SCRAPER_DATABASE_URL` | Database admin and application roles | Render → database → credentials (admin); `APP_DB_PASSWORD` then `python scripts/apply_migrations.py` re-syncs the `ceopro_app` password | `SCRAPER_DATABASE_URL` contains a password inside the URL. |
| 5 | `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Object storage (uploads, campaign images) | The storage provider (MinIO/R2/S3) console, then the app's environment | |
| 6 | `GRAFANA_ADMIN_PASSWORD` | Monitoring dashboards | Grafana admin settings | |
| 7 | `SEARXNG_SECRET` | SearXNG instance secret | The SearXNG deployment's settings | |
| 8 | `REDIS_URL` | Queue/cache | Only if a password was ever added to it in a hosted environment | The exposed value has no password. |

| 9 | `SMTP_USERNAME`, `SMTP_PASSWORD` | Outgoing email (sign-up codes, password resets) | The email provider's console | Found in history by the system audit (`docs/FINAL_SYSTEM_AUDIT.md` 3.1), in `KEYS_AND_ACCOUNTS_NEEDED.md` / `.env.example`, not only the root `.env`. |
| 10 | `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNTS`, `HUGGINGFACE_API_TOKEN(S)`, `GEMINI_API_KEYS`, `TOGETHER_API_KEYS`, `HORDE_API_KEYS`, `POLLINATIONS_API_KEYS` | Hosted image-provider accounts | Each provider's dashboard: delete and recreate | Same finding. Hugging Face's token is already rejected (expired/revoked). The self-hosted image server needs none of these. |

Non-secret settings in the same file (pool sizes, stream names, timeouts, the fixed service-actor id) need no action.
The system audit compared values (never printing them) and found 16 of the owner's 17 current credential values in
history; the newer Groq key created after those commits is not in it.

## Optional: purge history

Rotation is what makes the leak harmless; purging only reduces further spread. If wanted: `git filter-repo
--path .env --invert-paths` on a fresh mirror clone, force-push every branch and tag, ask GitHub Support to clear
cached views and pull-request refs, and tell every collaborator to re-clone. This rewrites history for everyone
and is the repository owner's decision; the assistant has not done it.

## Already in place to prevent a repeat

- `.env` files are ignored (`.gitignore`), and CI (`pr-checks.yml`, first backend step) fails any change that
  tracks a `.env` file or Python bytecode.
- `secret-scan.yml` scans pushes.
- Credentials are read from the environment only; `backend/.env.example` holds names with empty values.

## Also seen during the 2026-10-22 work

- The Hugging Face token injected into the development sandbox (`ceopro-deploy`) is **expired**; replace it with a
  fine-grained token (Inference Providers only) if Hugging Face is used.
- While checking which hosts the exposed URLs point at, a malformed `DATABASE_URL` value caused part of the
  already-exposed database password to appear in the session's tool output. It was not written to any file or
  commit; it is covered by rotation #4.
