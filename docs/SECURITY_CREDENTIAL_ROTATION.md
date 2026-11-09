# Credential rotation runbook

This document lists setting **names only, never values**. Two incidents are covered:

1. **2026-11-09 (OPEN): production secrets stored as plaintext variables in the owner's agent cloud
   environments.** Ordered runbook below.
2. **2026-10-19 (OPEN): credentials committed to public Git history.** Inventory at the end of this file.

## 2026-11-09: production secrets in agent cloud environments

`JWT_SECRET`, `DATABASE_URL` (contains the Neon owner password), `APP_DB_PASSWORD` (`ceopro_app`), `REDIS_URL`
(Upstash password), `BREVO_API_KEY` / the Brevo SMTP key, `GROQ_API_KEY` (and `POSTGRES_PASSWORD`, `RENDER_API_KEY`, per
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
- **One secret per deploy**, verify, then the next. Session 1 deploys only with the owner's separate approval for that deploy. Each step below says what keeps customers working, how to
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
| Sign-in | a test account signs in on keelai.net and the dashboard loads; a tab that was **already signed in before the deploy** keeps working (no sign-out) - except the JWT step, where it must be signed out |
| Email | request a password-reset code for a test account: it arrives |
| Assistant | ask the assistant one question: an AI-written answer (not the "sources only" fallback) |
| Billing (read-only) | the Billing page loads for a test tenant; no Stripe action is needed |

### Step 0 - prerequisites (no secret changes)

1. Owner removes the variables from the `Default` agent environment (above).
2. PR `fix/jwt-key-rotation-overlap` (adds `JWT_SECRET_PREVIOUS`) is merged by the owner and **deployed by
   Session 1**; Session 2 verifies the deploy with the table above. Option B of step 1 (future routine rotations) must not be used before this: code
   without it ignores `JWT_SECRET_PREVIOUS` and the rotation would sign everyone out.
3. Session 1 notes the current live deploy id of each KEEL service as the code rollback target, and completes
   the inventory above.
4. Neon: confirm a restore point exists (Neon -> project -> Backup & Restore / branch history; free plan keeps a
   short history window). No data changes in this runbook, but the owner password grants full access.

Step 1 (hard rotation, decided for this incident) and steps 2-6 do not depend on the PR and can go first if its merge is delayed.

### Step 1 - `JWT_SECRET`

How the overlap works (`backend/src/ai/core/jwt_keys.py`): new tokens are signed **only** with `JWT_SECRET`;
verification tries `JWT_SECRET`, then `JWT_SECRET_PREVIOUS`. `exp` stays required; sign-out revocation, the
password-change cut-off and `credential_version` checks apply to both keys unchanged. A token that matched only
`JWT_SECRET_PREVIOUS` is honoured until it expires but **never re-issued under the new key**: renewal, switching or creating a workspace and changing the password all answer 401 (`security.get_current_key_context`), and
any token whose sign-in time (`auth_time`) is in the future is refused. Both close a review finding on #107: a
token forged with the old key, with a far-future `auth_time`, could otherwise be renewed into a new-key session
that outlived the rotation and was never capped by `SESSION_MAX_HOURS`.

Consequence: **with either option below, every signed-in user signs in once more.** The overlap only lets them
finish what they are doing (up to `JWT_EXPIRE_MINUTES`, 120) first. No option is both disruption-free and safe
against someone who holds the old key - during the overlap that person can still mint sessions that last until
the old key is removed.

**Owner decision (2026-11-09 ~10:55 UTC, relayed by Session 2 and Session 1): hard rotation, no overlap.**
The exposed key must stop being accepted immediately; everyone signing in again is acceptable.
**Never set `JWT_SECRET_PREVIOUS` for this rotation.** The overlap (option B below) is kept only for future
routine rotations of a key that is not known to be exposed.

Steps for this rotation (A - hard rotation):

1. Owner, Render dashboard -> `ceopro-ai-new` -> Environment: replace `JWT_SECRET` with a new value (Render's
   *Generate* button, or `openssl rand -hex 32` on the owner's own machine). Repeat on every other KEEL service
   that holds `JWT_SECRET`. Do not add `JWT_SECRET_PREVIOUS`. Save; Session 1 deploys (with owner deploy
   approval) and watches it go live. `security.py` reads `JWT_SECRET` at start, so the new deploy uses it.
2. Verify (Session 2, standard table plus):
   - a tab signed in **before** the deploy gets 401 on its next request and is asked to sign in (proves the old
     key is refused);
   - a new sign-in works, and its renewal works (stay active ~10 minutes before expiry, or call
     `POST /auth/refresh` with the new token: 200);
   - the deploy logs show no `JWT_SECRET_PREVIOUS` line and no `[error] JWT_SECRET...` line.
- Rollback: **never restore the old value** - it is exposed. If new sign-ins fail, the value in Render is wrong
  (for example cut short): generate another, deploy. Fix forward.
- Customer impact: every user signs in once, at the deploy.
- Side effects: the Overture cache is signed with `JWT_SECRET` when `OVERTURE_CACHE_SIGNING_KEY` is unset, so
  it is rebuilt once (performance only). Sign-out revocation entries are keyed by token id and simply expire.
  Nothing else signs with `JWT_SECRET` (Shopify OAuth has its own key).

Option B - overlap, for future routine rotations only (needs #107 deployed): add `JWT_SECRET_PREVIOUS` with
exactly the old value and set a new `JWT_SECRET`. Old-key tokens keep working until they expire (at most
`JWT_EXPIRE_MINUTES`, 120) but are never renewed, so each user signs in once within 2 hours. Remove
`JWT_SECRET_PREVIOUS` after `JWT_EXPIRE_MINUTES` + 1 hour (never longer than `SESSION_MAX_HOURS`). The logs
show a `[warning] JWT_SECRET_PREVIOUS: is set ...` line while it is set.

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

### Step 6b - Render API key (`RENDER_API_KEY`)

It was also a plaintext variable in `ceopro-ai` (removed 04:30). It can reach every service in the Render
account, not only KEEL. Several keys can exist at once: no window.

1. Owner, Render -> Account Settings -> API Keys: create a new key; save it as the proxy-injected network
   secret for `api.render.com` on the agent environment (claude.ai -> environment -> network secrets; never as a
   plain variable).
2. Verify: Session 1 reads one KEEL deploy status through the proxy.
3. Then owner deletes the old key in Render.
- Rollback: before deleting the old key, restore it as the network secret.

### Step 7 - finish

1. Confirm no KEEL service has `JWT_SECRET_PREVIOUS` set (nothing to remove for this hard rotation).
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
| 3 | `JWT_SECRET` | Signs every login session | Render environment; generate with `python -c "import secrets;print(secrets.token_hex(32))"` | See step 1 above (hard rotation or `JWT_SECRET_PREVIOUS` overlap). Anyone with the old secret can forge a session for any company. |
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
