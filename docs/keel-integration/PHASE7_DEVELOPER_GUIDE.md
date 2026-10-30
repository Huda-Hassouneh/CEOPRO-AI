> Current fresh-clone startup: [root developer commands](../LOCAL_DEVELOPMENT.md). The guide below describes the earlier specialist/WSL workflow and historical evidence; its fixed ports and recorded migration counts are not the new default.

# KEEL contributor setup and verification

This is the current Windows/PowerShell handoff. It uses the reusable isolated verification environment and the repository's WSL development scripts. It never requires production credentials or databases.

## Prerequisites

- Git and Windows PowerShell.
- Docker Desktop using WSL 2 and integration enabled for the selected Linux distribution.
- Current Ubuntu LTS in WSL 2, Python 3.11, Node.js 20+, npm and Bash.
- At least 15 GB free on C: before full dependency installation; 10 GB is a preferred minimum for the smaller verification workflow.
- Chromium installed for browser tests.

Check disk space in PowerShell:
~~~~powershell
Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'" | Select-Object @{N='FreeGB';E={[math]::Round($_.FreeSpace/1GB,2)}}
~~~~
Stop disk-heavy work below 5 GB. Keep full development clones inside the WSL Linux filesystem for Docker and Node performance.

## Clone and choose a setup path

Clone the team-supplied URL and select the integration branch:
~~~~bash
git clone <team-provided-repository-url> keel
cd keel
git switch integration/keel-full-migration
~~~~

Use one of these paths:

- Focused acceptance: tools/keel-verification from PowerShell. It reuses the task-owned PostgreSQL 17/pgvector, Redis, MinIO, Python venv, frontend dependencies and Chromium.
- Full development: WSL Bash, ./keel setup once, then ./keel start. The .devcontainer scripts and keel wrapper implement this path. RUNNING_LOCALLY.md and CODESPACES_DEVELOPMENT.md provide more detail. Full setup installs AI runtime dependencies, including CPU Torch; it is larger than the verification environment.

From PowerShell, enter WSL with wsl.exe. Run the full stack commands inside the Linux checkout.

## Settings and credentials

Tracked templates:
- backend/.env.example covers backend, database, role password, Redis, storage, auth, CORS/email, billing, providers, AI, worker retries/schedules and operations.
- frontend/.env.example covers VITE_API_BASE_URL, optional Spline/Sentry browser settings, and optional VITE_SUPPORT_EMAIL/VITE_SENTRY_RELEASE.
- backend/KEYS_AND_ACCOUNTS_NEEDED.md and docs/SECRETS.md explain sourcing and rotation.

The templates are the source for supported names. Do not create a duplicate root template. Full local setup copies them to ignored backend/.env and frontend/.env. Never commit secrets or put them in logs or browser fixtures.

Core settings include JWT_SECRET, DATABASE_URL, APP_DB_PASSWORD, Redis and a valid CREDENTIAL_VAULT_MASTER_KEY. Local Compose also needs POSTGRES_PASSWORD; local object storage uses MINIO_* settings. FRONTEND_BASE_URL, APP_BASE_URL, CORS_ALLOWED_ORIGINS and VITE_API_BASE_URL must match actual local origins.

Migrations 1–103 run with the schema-owner DATABASE_URL; the migration runner synchronizes the restricted ceopro_app password from APP_DB_PASSWORD. Runtime requests/workers use restricted-role connections. Do not use the schema-owner account for customer traffic. Migration 103's durable inbox functions and RLS rely on restricted privileges and FORCE RLS.

Groq, search/scrape providers, Stripe, Shopify OAuth (SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET, SHOPIFY_REDIRECT_URI; FRONTEND_URL is the trusted callback destination and SHOPIFY_REQUEST_ALL_ORDERS defaults false), WooCommerce store keys, Google Places, SMTP and hosted image providers are optional. Empty optional values disable a provider or return an unavailable state. A free/keyless image provider can still call the internet; the Phase 7 browser smoke does not invoke providers. Use only Stripe test credentials for local sandbox work.

## Full local development on WSL

From repository root:
~~~~bash
./keel setup
./keel start
~~~~

Setup copies the examples only if local ignored files do not exist, generates a per-checkout JWT secret and Fernet vault key, installs Python packages into backend/.venv, and installs frontend packages. Keep a stable vault key if local connector credentials are stored.

Start starts Postgres/pgvector, Redis and MinIO, applies migrations, and runs FastAPI and Vite. Open http://localhost:5173. API health/readiness are /health and /health/ready on port 8000. Local API documentation is /docs.

Optional synthetic demo data:
~~~~bash
./keel seed
~~~~
It prompts for a password locally. Accounts exist only in the database you seeded; see RUNNING_LOCALLY.md for demo addresses.

### Workers

Run market worker processes in a separate WSL terminal:
~~~~bash
./keel workers
~~~~
The supervisor runs price collection, analysis, discovery, enrichment, connectors and maintenance. KEEL_WORKERS can select those supported worker names, for example discovery,connectors.

Start the independent forecasting and marketing image consumers from backend/ with the same configured environment:
~~~~bash
python -m src.ai.forecasting.consumer
python -m src.ai.marketing.image_worker
~~~~
The API process starts discovery refresh, billing maintenance and notification digests as configured in backend/src/ai/main.py. Avoid duplicate instances. Tenant-scoped workers require configured active service actor identities under existing contracts.

Press Ctrl+C in each app/worker terminal to stop it. ./keel stop stops development Compose services and preserves volumes. Restart with ./keel start. Do not use docker compose down -v as routine cleanup.

## Reusable Windows verification environment

From PowerShell in tools/keel-verification:
~~~~powershell
.\Initialize.ps1
.\Install-Python.ps1   # first use; no ML model weights
.\Reset-Database.ps1   # only the dedicated keel_verification DB
~~~~
Initialize reuses containers and venv. Synthetic credentials live outside Git in %LOCALAPPDATA%\KEEL\verification\compose.env with current-user ACLs and process-scoped environment. PostgreSQL/MinIO volumes persist. The setup role is for migration; tests/application requests use ceopro_app where relevant. Keep ceopro_app non-superuser and NOBYPASSRLS.

Common focused commands:
~~~~powershell
.\Test-Backend.ps1 src/ai/tests/test_rls_integration_db.py
.\Test-Backend.ps1 tests/keel_integration/test_native_phase1a.py
.\Test-Frontend.ps1
.\Serve-Backend.ps1
.\Serve-Frontend.ps1
.\Prepare-BrowserFixture.ps1
.\Test-Browser.ps1 -IncludeDataImport -IncludeNotifications -IncludeProducts
.\Test-HandoffBrowser.ps1
.\Test-MigrationUpgrade.ps1
~~~~

Test-Backend runs pytest with disposable DB, role, worker actor and storage config. Pass focused paths, not every suite by default. Test-Frontend runs UI tests, ESLint and Vite build. Browser tests need FastAPI/Vite from separate terminals and a synthetic fixture. Prepare-BrowserFixture keeps its credentials outside Git.

The isolated auth/platform runner backend/scripts/auth_browser_verification.py uses local test-only SMTP, requires aiosmtpd and a dedicated localhost BILLING_TEST_DATABASE_URL named keel_billing_test or keel_billing_test_<suffix>. Do not point it at keel_verification or any development/production DB.

Test-MigrationUpgrade tests populated 1–102 to 103 and rerun behavior. Reset-Database applies 1–103 to keel_verification via backend/scripts/apply_migrations.py.

### Safe reset and troubleshooting

Reset-Database drops/recreates only keel_verification and its test ceopro_app role in the named container, then reapplies migrations. It destroys that database's synthetic data but not normal development data or persistent container volumes. Do not run while another task needs its fixture data.

Stop.ps1 stops only the named verification services and keeps volumes/venv. Never run broad Docker prune or delete user caches. Remove only a uniquely identified temporary database/file created by your task.

The verification venv excludes Torch/Transformers/model weights. Fixtures are not live provider certification. Full .devcontainer/setup.sh installs AI requirements and CPU Torch; check disk/network first.

- Docker unavailable: start Docker Desktop and enable WSL 2 integration; verify docker info from WSL. Do not create a workaround stack.
- Readiness failure: inspect current service logs and DB/Redis/MinIO host ports.
- RLS failure: migrations use schema-owner URL and APP_DB_PASSWORD; app paths use ceopro_app, never a DB superuser.
- Port busy: do not kill an unknown process. Confirm its PID or use KEEL_BACKEND_PORT / KEEL_FRONTEND_PORT with keel.
- AI unavailable: inspect configured provider and honest options/errors; do not install large models as generic startup repair.
- Migration failure: preserve logs and test in a disposable DB; never edit applied migrations.
- Local email is not configured: use synthetic local flows; do not enable unsent message body logging where real users exist.