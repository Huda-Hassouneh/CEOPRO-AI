# Running KEEL on your own machine

This guide is self-contained: it doesn't depend on any particular person,
session or machine. Use it to open the product and inspect its current state.
See `CURRENT_STATUS.md` for what is finished and what remains.

**Quick start** (any machine with Docker, Python 3.11 and Node 20+, or a Codespace):

```bash
./keel setup     # once
./keel start     # every time - then open http://localhost:5173
```

`./keel status` shows what is running, `./keel stop` stops the databases,
`./keel workers` runs the background workers, `./keel seed` loads the demo companies and `./keel test` runs every check.
The sections below explain each step and the manual equivalents.

There are two ways to run it:

- **A. GitHub Codespaces.** Nothing to install; it runs in the browser.
- **B. Your own computer.** Uses Docker, Python 3.11 and Node 20+.

Both run the same code: the `main` branch of
`github.com/Huda-Hassouneh/360-Radar`.

---

## What runs where

| Part | What it is | Port |
|---|---|---|
| Postgres 16 + pgvector | The only database (all business data, row-level security per company) | 5432 |
| Redis | Rate limiting, caches, background job streams | 6379 |
| MinIO | File storage (uploaded sales files, documents, campaign images) | 9000 (console 9001) |
| Backend | FastAPI app, `backend/src/ai/main.py` | 8000 |
| Frontend | React + Vite app, `frontend/` | 5173 |

---

## A. GitHub Codespaces

1. Open the repository on GitHub, then choose **Code → Codespaces → Create
   codespace on main**. A 4-core machine is recommended, because the AI models
   need memory.
2. Wait for setup to finish; it runs automatically.
   - `.devcontainer/setup.sh` installs the dependencies and creates
     `backend/.env` and `frontend/.env`.
   - `.devcontainer/start-services.sh` starts Postgres, Redis and MinIO, then
     applies the database migrations.
3. Add your Groq key: open `backend/.env` and set `GROQ_API_KEY=` to your key.
   A free key is available at https://console.groq.com. Without it, everything
   works except the AI assistant's answers. `backend/.env` is git-ignored and
   stays on your machine; in a Codespace use Codespaces secrets instead. All
   names and permissions: docs/SECRETS.md.
4. Start the backend in terminal 1:
   ```bash
   cd backend && source .venv/bin/activate && set -a && source .env && set +a
   uvicorn src.ai.main:app --host 0.0.0.0 --port 8000
   ```
5. Start the frontend in terminal 2:
   ```bash
   cd frontend && npm run dev -- --host 0.0.0.0
   ```
6. Open the forwarded **5173** address from the **Ports** tab and sign up.

More detail is in `CODESPACES_DEVELOPMENT.md`.

---

## B. Your own computer (Linux, macOS, or Windows with WSL 2)

You need **Docker** (Docker Desktop on Mac/Windows), **Python 3.11**
(`python3.11` on the PATH), **Node.js 20+**, and about 10 GB of free disk
space (the AI models are large).

```bash
git clone https://github.com/Huda-Hassouneh/360-Radar.git
cd 360-Radar

# One time: creates backend/.env and frontend/.env from the templates (with a
# random JWT_SECRET and localhost database settings), then installs the
# backend (Python venv) and frontend (npm) dependencies.
bash .devcontainer/setup.sh

# Every time: starts Postgres + pgvector, Redis and MinIO in Docker and
# applies the database migrations. The first run builds MinIO from source,
# which takes about 5 minutes once.
bash .devcontainer/start-services.sh
```

Then put your Groq key in `backend/.env` (`GROQ_API_KEY=...`) and run
`./keel start`, which starts both apps in one terminal. To start them
separately instead:

**Terminal 1, backend:**
```bash
cd backend && source .venv/bin/activate
set -a && source .env && set +a
uvicorn src.ai.main:app --host 0.0.0.0 --port 8000
```

**Terminal 2, frontend:**
```bash
cd frontend
npm run build && npm run preview -- --host 0.0.0.0 --port 5173   # production build
#   or, while developing:  npm run dev -- --host 0.0.0.0
```

Open **http://localhost:5173** and sign up, or seed the demo companies (see
below). The backend's health check is at http://localhost:8000/health and
its API reference is at http://localhost:8000/docs.

To stop everything, press Ctrl+C in both terminals, then run
`cd backend && docker compose stop`. Your data is kept in Docker volumes.

### Configuration names (values are never committed)

`setup.sh` fills in working local values for the required ones. To set
them yourself (for example on a server), every name is explained in
`backend/.env.example`.

| Needed for | Variable names |
|---|---|
| Database (required) | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `DATABASE_URL`, `APP_DB_PASSWORD` |
| Sign-in (required) | `JWT_SECRET` (a long random string) |
| Cache / rate limits (required) | `REDIS_HOST`, `REDIS_PORT` (or `REDIS_URL`) |
| File storage (required) | `MINIO_ENDPOINT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` |
| Browser access (required) | `CORS_ALLOWED_ORIGINS` (e.g. `http://localhost:5173`), `FRONTEND_BASE_URL` |
| AI assistant answers | `GROQ_API_KEY` (optional: `GROQ_MODEL`, `GROQ_MAX_TOKENS`) |
| Emails (codes, invitations) | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `EMAIL_FROM_ADDRESS` (if unset nothing is sent; set `EMAIL_LOG_UNSENT_BODIES=true` in a local `.env` to see codes in the backend log, or set a password directly with `python -m scripts.set_password --email you@example.com`) |
| AI images (optional) | `MARKETING_IMAGE_PROVIDER` and that provider's settings; `MARKETING_BACKGROUND_REMOVAL_PROVIDER=rembg` for background removal |
| Competitor discovery and web search (optional) | `GOOGLE_PLACES_API_KEY`, `GOOGLE_CUSTOM_SEARCH_API_KEY`, `GOOGLE_CUSTOM_SEARCH_CX`, `APIFY_API_TOKEN`, or `SEARXNG_INSTANCE_URL` |
| Logging | `LOG_LEVEL` (default `INFO`) |

`frontend/.env`: set `VITE_API_BASE_URL` to the backend address
(`http://localhost:8000`).

---

## Demo data (seven realistic companies)

The repository includes a generator for seven businesses with 18 months of
history: grocery, fashion, restaurant, salon, industrial B2B, electronics and
repair, and consulting. Each comes with competitors, competitor prices,
customer reviews and business documents. To load them into **your** running
instance, with the backend up, run `./keel seed` (it asks for the password
the demo sign-ins will use), or the steps it runs:

```bash
cd backend && source .venv/bin/activate
python -m scripts.demo_companies.generate --out-dir /tmp/demo --end "$(date +%F)"
python -m scripts.demo_companies.seed   --api http://localhost:8000 --data-dir /tmp/demo --password '<a password you choose>'
python -m scripts.demo_companies.verify --api http://localhost:8000 --data-dir /tmp/demo --password '<the same password>'
```

`verify` should report `0 failing check(s)`. The demo sign-ins then exist on
your instance, all with the password you chose above:

| Company | Sign-in |
|---|---|
| Zaytouna Fine Foods (grocery, Jordan, JOD) | `rania@zaytouna.keel-demo.example` |
| Atlas Couture (fashion, Morocco, MAD) | `salma@atlas.keel-demo.example` |
| Beit Al Shawarma (restaurant, UAE, AED) | `khaled@beit.keel-demo.example` |
| Nour Beauty Lounge (salon, Saudi Arabia, SAR) | `huda@nour.keel-demo.example` |
| Petra Industrial Supplies (B2B, Jordan, JOD) | `samer@petra.keel-demo.example` |
| ByteFix Electronics (electronics + repair, Egypt, EGP) | `mostafa@bytefix.keel-demo.example` |
| Clarity Conseil (consulting, France, EUR) | `julien@clarity.keel-demo.example` |

These accounts live in the database of whichever instance you seed. A fresh
instance has none until you run `seed`. The `.example` addresses never receive
email.

---

## Plans and usage allowances

Each company's allowances come from its plan: Standard, Plus, Pro or Custom
(keys `starter`, `growth`, `enterprise`, `custom`). Reports, Data Credits and
AI Credits are counted per billing period; products, team seats and storage
are counted live. Every paid provider call is paid from the company's Data or
AI Credits and refused when the provider has no confirmed price - see
`docs/SUBSCRIPTIONS_AND_CREDITS.md` for the budgets, how to set prices
(`python -m scripts.billing_admin`) and the counting rules. These allowances
are separate from the technical safety limits (10 MB per upload, 20 MB per
assistant document), which apply to everyone.

- A company without an assigned plan has no access (`UNASSIGNED_PLAN_ACCESS=none`).
  Sign-up starts a free trial; `./keel seed` puts the demo companies on Plus.
  `UNASSIGNED_PLAN_ACCESS=default` gives such companies `DEFAULT_PLAN_KEY`
  instead (single-company installs only).
- Plans and limits are stored in `usage_plans` and `usage_plan_limits`. A NULL
  limit means unlimited.
- To put a company on a plan (an operator task, or done by a billing service),
  connect as the database owner and run:
  ```sql
  INSERT INTO tenant_plan_assignments (tenant_id, plan_key, status, current_period_start, current_period_end, source)
  SELECT tenant_id, 'standard', 'active', DATE '2026-10-01', DATE '2026-10-31', 'manual'
  FROM companies WHERE business_name = 'Your Company'
  ON CONFLICT (tenant_id) DO UPDATE SET plan_key = EXCLUDED.plan_key, status = EXCLUDED.status,
      current_period_start = EXCLUDED.current_period_start, current_period_end = EXCLUDED.current_period_end;
  ```
  Only the `active` and `trialing` statuses grant access. The application's
  own database role can read plans but cannot change them.
- `AI_REQUESTS_PER_MINUTE_PER_COMPANY` (default 8) is a fairness cap, not an
  allowance: it stops a burst from one company from using up the shared AI
  provider's per-minute capacity for everyone.

## Checking the code

`./keel test` runs all of the following.

```bash
# Backend: unit tests, plus the live-database tests when AI_TEST_DATABASE_URL is set
cd backend && source .venv/bin/activate && set -a && source .env && set +a
export AI_TEST_DATABASE_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/$POSTGRES_DB"
python -m pytest -q src/

# Frontend: tests and the production build
cd frontend && node --test tests/*.test.mjs && npm run build
```

The same checks run on every pull request (`.github/workflows/`).

## Troubleshooting

- **The AI assistant says it is unavailable:** `GROQ_API_KEY` is missing or
  invalid. A "too many questions" message means the Groq account's per-minute
  limit was reached; wait the number of seconds shown.
- **Uploads fail:** MinIO isn't running. Run `docker compose up -d minio` in
  `backend/`.
- **"Connection refused" on 5432:** Postgres isn't running. Run
  `docker compose up -d postgres` in `backend/`.
- **You need a password-reset code locally:** without SMTP, the code is written
  to the backend's log.
- **`docker compose` says "429 Too Many Requests" from docker.io:** Docker
  Hub limits anonymous image pulls. Run `docker login` (a free Docker
  account raises the limit), or wait an hour and retry.
- **`docker compose run --rm migrate` can't install `psycopg2-binary`**
  (behind a corporate proxy or TLS-inspecting network): run the same
  migration runner from the backend's own environment instead:
  ```bash
  cd backend && source .venv/bin/activate && set -a && source .env && set +a
  python scripts/apply_migrations.py
  ```

