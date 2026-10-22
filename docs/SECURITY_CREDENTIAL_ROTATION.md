# Credentials exposed in public Git history: what must be rotated

**Status: OPEN. Not resolved.** Removing the file from the latest commit (done in `4c5536e`) does not remove it
from history: anyone can still read it at commit `128dba2` (merged 2026-10-19) of this public repository, and it
may already be in forks, clones and search-engine caches. Every value in it must be treated as known to the
public. This document lists names only, never values.

Exposed in three places: the repository-root `.env` (commit `128dba2`) and earlier versions of
`backend/KEYS_AND_ACCOUNTS_NEEDED.md` and `.env.example` (2026-10-13 to 2026-10-19; see the system audit). The root
`.env` Its URLs point at Docker service names (`postgres`, `searxng`) and
`localhost`, so it was written for the Docker/local setup. That does not make it harmless: if any of these values
was ever reused on Render (staging or production), in a Codespace secret, or for another account, that place is
exposed too. Whether that happened cannot be checked from the development sandbox.

## Rotate (owner action, in this order)

| # | Name(s) | What it protects | Where to rotate | Notes |
|---|---|---|---|---|
| 1 | `GROQ_API_KEY` | Paid/rate-limited Groq account | console.groq.com → API Keys: **delete** the old key, create a new one, put it in Render's environment (never in chat or Git) | The key reachable from the sandbox already returns 401, which suggests it was revoked; confirm it is deleted. |
| 2 | `CREDENTIAL_VAULT_MASTER_KEY` | Encrypts customers' stored connector credentials (database/API connectors) | Generate a new key; set it as `CREDENTIAL_VAULT_MASTER_KEY` and the old one in `CREDENTIAL_VAULT_PREVIOUS_KEYS`; run `python -m scripts.vault_key rewrap`; then remove the old key | If the exposed key was ever used outside local Docker, also ask affected customers to rotate the connector passwords they stored. |
| 3 | `JWT_SECRET` | Signs every login session | Render environment; generate with `python -c "import secrets;print(secrets.token_hex(32))"` | Rotating signs everyone out. Anyone with the old secret can forge a session for any company. |
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
