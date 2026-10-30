# Running KEEL locally

Use this guide from an ordinary repository checkout. No personal folder,
shared demo password, existing `.dev` directory or legacy repository is needed.

## Prerequisites

| Tool | Requirement | Check |
|---|---|---|
| Git | On PATH | `git --version` |
| Python | 64-bit CPython 3.11 or 3.12 | `python --version` |
| Node.js / npm | Node 24 recommended; launcher accepts 22.12+ | `node --version`; `npm --version` |
| Docker | Running Linux-container engine; local context | `docker info` |
| Compose | Docker Compose 2.20+ | `docker compose version` |
| PowerShell | Windows PowerShell 5.1+ | `$PSVersionTable.PSVersion` |

Allow several GB for Python/Node dependencies and container images. Internet
access to configured package/container registries is needed on first setup.
Tesseract, Chrome/Chromium, Stripe CLI, local model weights and hosted provider
accounts are optional and only needed for their respective workflows.
Windows is the measured native onboarding platform; Linux/macOS share the
Bash/Python entry point but were not executed in the current verification.

## First run

Install Git, CPython 3.11/3.12 (64-bit), Node 24 LTS and Docker Desktop with Linux containers. Run `python --version`, `node --version`, `docker info` and `docker compose version`.

From the checkout root:

```powershell
.\dev.ps1 setup
.\dev.ps1 up --mode full
.\dev.ps1 status
```

The Bash form is `bash dev.sh setup`, then `bash dev.sh up --mode full`.
See [measured verification and limits](REPOSITORY_READINESS.md) before assuming
platform-specific dependency or binary support.

Setup checks prerequisites before installing, creates its own `.dev/venv` and uses the repository dependency constraints. It uses `npm ci`, never an undeclared shared node_modules directory. Dependency fingerprints make repeated setup inexpensive. If you deliberately remove packages from an existing venv, remove only `.dev/dependencies.json` to request dependency reinstallation; do not delete configuration or volumes.

Setup does not start application processes or populate a database. `up` starts infrastructure, runs forward migrations, verifies pgvector/restricted login/FORCE RLS, starts API/workers, verifies readiness, then starts Vite and checks its actual API proxy.

### Environment files and first database

For **core local development, copy no environment file**. Setup generates
`.dev/config.json`, a checkout ID, free ports and fresh DB/JWT/vault/storage
credentials. Keep that file private and retain it for the life of its volumes.
Root, backend and frontend `.env` files are ignored by this launcher.

For optional integrations only, copy `tools/dev/integrations.env.example` to
`.dev/integrations.env`, fill the relevant values from your authorized test
accounts, then restart. Empty provider keys are valid for the core stack.
[Configuration](ENVIRONMENT_VARIABLES.md) distinguishes generated values from
optional keys; the backend/frontend `.env.example` files are manual deployment
references, not files this workflow asks you to populate.

The PostgreSQL image creates one empty checkout-owned database on first use.
`up` applies `Final_schema.sql` and pending ordered migrations via
`scripts/apply_migrations.py`, provisions restricted runtime credentials and
initializes feature, plan and approved provider-pricing catalogs. It does not
create customers, paid subscriptions, Stripe prices or synthetic sales.
Repeated migration runs retain applied history; approved Groq defaults preserve
configured rates. See [database and catalog boundaries](DATABASE.md).

### First successful startup and account

Success prints `READY`, frontend/API/docs/Mailpit URLs and optional capability
availability. `status` should report API database/Redis readiness, frontend,
eight full-mode workers and four healthy infrastructure containers. Worker
readiness does not certify merchant synchronization or AI generation.

| Service | Preferred address | Purpose |
|---|---|---|
| Frontend | `http://127.0.0.1:5173` | Signup and customer interface |
| API / docs | `http://127.0.0.1:8000` / `/docs` | HTTP API and interactive schema |
| Readiness | API `/health/ready`; frontend `/api/health/ready` | Database/Redis and proxy check |
| Mailpit | `http://127.0.0.1:58025` | Captured local verification/digest email |
| MinIO console | `http://127.0.0.1:59001` | Private local object-storage administration |

These are **preferred ports**, not universal addresses. Setup selects free ports
and persists them. Open the printed URLs; `doctor` reports your actual ports.
MinIO's generated login remains in private local config; never publish it.

1. Open the frontend's signup page and use a new synthetic email and password.
2. Open the printed Mailpit inbox and submit the actual verification code.
3. Sign in and complete the business/onboarding steps. The verified account
   receives its own tenant and normal eligible trial, not another user's data.
4. Inspect Dashboard and Products. Empty business data is expected; import
   reviewed files or create disposable records through the application.
5. Check the optional-capability messages. Without provider keys, live AI,
   Stripe Checkout and merchant connections are unavailable by design.

Signup creates a **Tenant Owner**, not a Platform Owner. Platform access requires
the existing authorized invitation flow or the explicit operator bootstrap
`python -m scripts.bootstrap_platform_owner --help` from `backend/`.
That command requires a verified existing user, installation authority and
reviewed bootstrap arguments; it is not necessary for customer development.
Never grant platform access by directly changing membership rows.

### Teammate onboarding checklist

- [ ] Open the root README and choose the intended team branch.
- [ ] Verify prerequisites; run `setup` without copying another checkout's secrets.
- [ ] Run `up --mode full`; use its printed frontend and Mailpit URLs.
- [ ] Confirm `status`, API readiness and all expected workers.
- [ ] Complete signup and real email verification; check the new workspace.
- [ ] Find the feature's code in [Features](FEATURES.md) and run its focused
  [tests](TESTING.md). Configure only the optional integration you need.
- [ ] Run `down` when finished; volumes/config remain for the next `up`.

## Modes and ownership

- `up` defaults to **full**: all eight supported workers.
- `up --mode core`: forecast, image and connector workers.
- `restart` keeps the last successful mode.
- Stop before changing mode: `down`, then `up --mode full`.

Remote/TCP/SSH Docker contexts are rejected; only a local Unix socket or Windows named pipe is supported. The global Docker context is never changed. Each checkout receives a random Compose project ID, labeled containers/volumes, a dedicated DB and Redis instance. Ports bind to loopback and are selected once from available defaults. No existing API, DB, Redis or runtime is adopted. Native worker metrics use their existing binding behavior; avoid exposing development hosts to untrusted networks.

Python/Node processes record PID, creation time, executable and exact command line. Shutdown refuses identity mismatches. Infrastructure operations verify the checkout labels. A launch failure leaves evidence/resources for diagnosis; `down` safely stops owned resources while preserving data. There is no automatic volume removal or database reset.

Only one mutating developer command runs at a time. If interrupted, inspect `.dev/command.lock` and its PID before removing a proven stale lock.

## Commands

```powershell
.\dev.ps1 status
.\dev.ps1 doctor
.\dev.ps1 logs --tail 80
.\dev.ps1 logs --service connectors --follow
.\dev.ps1 infra
.\dev.ps1 migrate
.\dev.ps1 db-status
.\dev.ps1 db-check
.\dev.ps1 seed
.\dev.ps1 test
.\dev.ps1 test --suite frontend
.\dev.ps1 test --suite database
.\dev.ps1 restart
.\dev.ps1 down
```

`seed` generates optional import files only. It does not bypass email verification, assign a plan or create an owner account. The database test command creates a fresh test database in this checkout's own cluster, applies migrations twice and runs the existing native RLS tests. It retains the test DB and records its generated name in `.dev/test-databases.json`; it never runs on your application DB.

## Debugging and individual processes

Use log names `api`, `frontend`, `forecast`, `images`, `connectors`, `prices`, `analysis`, `discovery`, `enrichment`, `maintenance`.

Infrastructure logs can be inspected without exposing environment values:

```powershell
$id = (Get-Content .dev/config.json -Raw | ConvertFrom-Json).id
docker compose --project-name "keeldev$id" --project-directory . -f .dev/compose.json logs --tail 80 postgres
```

For a debugger, use the launcher environment builder; do not copy passwords into IDE files. In a root Python session using `.dev/venv`:

```python
import sys
sys.path.insert(0, "tools/dev")
import dev
dev.run([dev.PYTHON, "-m", "pytest", "-q", "src/ai/tests/test_main.py"],
        cwd=dev.ROOT / "backend", env=dev.environment(dev.config()))
```

The same pattern can run `python -m src.market_scraper.connector_worker`, or uvicorn with `--reload` and your debugger port. **Stop the launcher-owned instance first**; never run two queue consumers accidentally. Standard launcher API has no reload supervisor, so ownership/readiness remain deterministic. Restart after backend code changes. Vite hot reload handles frontend edits.

## Configuration

Ports and per-checkout secrets live only in `.dev/config.json`. Change ports while down, then restart; URLs/CORS/proxy are derived together. Optional settings are literal `NAME=value` lines in `.dev/integrations.env`, never shell expressions. Infrastructure/authority overrides are refused. Root/backend/frontend `.env` files and inherited provider keys are not loaded by this workflow.

`setup --models` installs the existing AI requirements. Tesseract OCR and optional browser-assisted scraping need OS binaries; see integrations. Setup itself installs dependencies; startup migrations initialize approved catalogs as described above.

## Existing workflows

`backend/docker-compose.yml` remains the legacy/Codespaces deployment topology, including telemetry and local LLM options. Its fixed container names/ports make it unsafe for parallel checkouts. The new command generates only a small isolated infra Compose file from the same service technologies and reuses the existing MinIO Dockerfile and migration/worker entry points. Do not mix its volumes with the new project.

`tools/keel-verification/` remains the specialist synthetic acceptance harness. Its reset commands are intentionally excluded from everyday development.

## Optional read-only browser smoke

Run dev.ps1 test --suite browser after startup with Chrome/Chromium installed (or set CHROMIUM_PATH in private integrations.env). It checks actual English/Arabic login/signup rendering, mobile RTL, the Python proxy/public plans and unauthorized owner denial. It creates no accounts, quotes or payments. Screenshots/results remain private under .dev/evidence.

Frontend test-file concurrency is bounded to two processes so simultaneous Vite SSR test servers do not exhaust a developer machine. Every existing assertion still runs.

If multiple Python versions are installed, Unix can select one with KEEL_PYTHON=python3.12 bash dev.sh setup. On Windows invoke a compatible interpreter explicitly against tools/dev/dev.py setup before using dev.ps1. Do not copy another checkout's venv.

## Reboot and isolated CI recovery

See [Testing](TESTING.md) for backend, authenticated browser, accessibility and audit suites. The [recovery reference](TEST_ENVIRONMENT_RECOVERY.md) explains retained test evidence. `test --suite backend`, `browser-ci` and `a11y` create fresh test databases and separate test Redis/storage. `test-cleanup` removes only disposable test containers, retaining databases and all normal volumes. No previous temp script or remembered port is required.
