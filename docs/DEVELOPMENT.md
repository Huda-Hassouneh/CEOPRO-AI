# Development and operations

> **18 October review update:** the custom competitor bridge and dependent Smart Alerts UI are suspended. The current team competitor source is restored unchanged. Earlier descriptions of active custom tracking below are historical. See [current review instructions](COMPETITOR_REVIEW.md).


## First clone

1. Install Node 24 and Docker Desktop with Compose v2; use Python 3.11/3.12 with `venv`. The full AI dependency set needs substantially more disk/downloads than the store adapter.
2. Run `npm.cmd run setup`. It copies missing root/backend/frontend/ai `.env` files and runs the two Node `npm ci` installs. It never overwrites an existing env file, migrates or seeds.
3. Edit root `.env`: set a local PostgreSQL administrator password and retain a consistent Compose project/volume identity. `POSTGRES_*` applies only on initial volume creation; changing that file does not change passwords in an existing volume.
4. Edit backend `.env`: set bootstrap/admin URL, app and all three worker URLs with distinct passwords, both JWT secrets, frontend origin and the integrations you intend to test. Percent-encode URL password special characters. Never switch the running API to the administrator URL.
5. Set frontend public API origin. Fill only the Python configuration needed by the chosen services. Copy the shared adapter secret identically into backend and AI; copy JWT_SECRET for insights; keep the encryption key stable.
6. Start infrastructure and initialize as below.

```powershell
docker compose up -d
docker compose ps
# Only for a brand-new EMPTY KEEL_DEV:
npm.cmd run db:init
npm.cmd run db:roles
```

The Docker POSTGRES_USER is the development migration administrator. `db:init` refuses a nonempty public schema, prepares historical role names required by applied SQL, then runs the existing Prisma migration chain once. `db:migrate` uses the same forward-only chain for an existing Prisma-managed database. Both refuse production mode and database names without DEV/TEST. They do not drop data, reset migrations or overwrite the app URL. The compatibility role `ceopro_ai_test_writer` is created with LOGIN but no password because historical SQL requires LOGIN; do not grant it credentials outside an isolated test environment. The two other compatibility aliases are NOLOGIN.

`db:roles` validates role identity, target host/database and unsafe role flags, then aligns passwords for app, market dispatcher, ingestion and notification roles in one transaction. Existing grants/RLS policies are retained. This is a deliberate DEV/TEST administration command, not an automatic startup action. The administrator needs CREATEROLE and ownership sufficient for migrations/extensions; root Docker's initial administrator meets development requirements. Production role provisioning belongs to the database operator.

### First owner, feature catalog and plans

From `backend/`, review the `OWNER_*` settings and run `npm.cmd run bootstrap:owner` with the separate BOOTSTRAP_DATABASE_URL. `bootstrap:admin` uses the ADMIN_* settings. Do not put owner passwords in shared files.

Feature/plan bootstraps are deliberate configuration changes, not restart commands. `bootstrap:features` rebuilds the feature catalog while preserving mappings; `bootstrap:stripe` / `bootstrap:plans` also create/update Stripe objects. Use a test-mode Stripe account and review `bootstrap:plans:dry-run` before writes. These scripts use DATABASE_URL: supply the administrative URL to that command's process only, and restore the runtime setting immediately afterward. Do not run the production-init script against an existing deployment just to obtain sample data. `prisma:seed` is optional DEV/TEST demo data and is not needed to synchronize a real store.

```powershell
# Example: temporary per-process setting for an intentional catalog command.
# Read the URL privately; do not paste it into a chat or commit it.
$previousDb = $env:DATABASE_URL
try {
    $env:DATABASE_URL = Read-Host 'Administrative DEV database URL'
    npm.cmd run bootstrap:features
    if ($LASTEXITCODE -ne 0) { throw 'Feature bootstrap failed' }
} finally {
    if ($null -eq $previousDb) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
    else { $env:DATABASE_URL = $previousDb }
}
```

The example is intended for a private terminal: Read-Host hides neither typed input nor the clipboard. Prefer your secret manager for shared/production work. Plan dry-run may require Stripe credentials too. Verify active tenant plan/capacity before importing a large catalog; increasing a CSV's row count does not override entitlements.

### Python profiles

```powershell
# From root: store-only dependencies, no ML downloads.
npm.cmd run setup:store
# Also install insights if needed:
.\ai\.venv\Scripts\python.exe -m pip install -r ai/requirements-insights.txt
# Full market/model toolchain instead (larger dependency set):
npm.cmd run setup:ai
```

The root launcher selects `ai/.venv` if present. Set KEEL_PYTHON in your shell before setup if multiple Python installations exist. API launchers load `ai/.env`; running uvicorn manually may need explicit environment loading. Backend launchers supply repository-relative collector paths and forward scraper/cost/vault settings from ai/.env. Prefer these wrappers over machine-specific absolute paths.

## Existing database / daily restart

Do not run init, seeds, catalog bootstrap or password rotation on every restart. From root:

```powershell
docker compose up -d
# After pulling a change with new migrations only:
npm.cmd run db:migrate
# Run in separate tabs as needed:
npm.cmd run dev:backend
npm.cmd run api:store
npm.cmd run worker:store-sync
npm.cmd run dev:frontend
```

The last four commands are long-lived; running them sequentially in one terminal blocks at the first one. To open the full integrated profile in Windows Terminal:

```powershell
$keelRoot = (Get-Location).Path
$commands = @('dev:backend','dev:frontend','api:store','api:insights','worker:store-sync','worker:dispatch','workers:market','worker:ingestion','worker:platform-notifications','worker:tenant-notifications')
foreach ($command in $commands) {
    wt.exe -w 0 new-tab --title "KEEL $command" -d "$keelRoot" powershell.exe -NoExit -Command "npm.cmd run $command"
}
```

Run only one copy of each profile during local troubleshooting. The two notification workers are different processes; `worker:notifications` in backend is an alias for the platform worker, not a third service. Store sync handles both Shopify and WooCommerce. Market dispatcher and Python market consumers are different jobs. Stop a tab with Ctrl+C; the Python supervisor shuts down its children. Neither command runs Docker for you.

### Health and connectivity

```powershell
Invoke-RestMethod http://127.0.0.1:5000/health
Invoke-RestMethod http://127.0.0.1:8001/health
Invoke-RestMethod http://127.0.0.1:8002/health
Test-NetConnection 127.0.0.1 -Port 5433
Test-NetConnection 127.0.0.1 -Port 6379
docker compose exec redis redis-cli PING
```

Health endpoints establish process liveness, not database authorization, model readiness or successful imports. The optional `db:check` also validates collector actor configuration; it is not a universal API-only health check. Inspect tenant job status and completed counts after an actual authorized action.

## Troubleshooting

- Two Postgres containers: `docker ps --format 'table {{.Names}}\t{{.Ports}}'` shows which exposes 5433. Root Compose must use the existing intended project/volume. Do not recreate another backend database or remove a volume.
- Password errors after restart: confirm URLs still target that volume; use `db:roles` only with the intended DEV administrator and configured passwords. `POSTGRES_PASSWORD` does not rotate an initialized database.
- Prisma missing table/client delegate: run `db:migrate`, then `npm.cmd --prefix backend run prisma:generate`, restart Node. A failed migration needs investigation; do not mark it applied or reset to hide the failure.
- RLS failure: retain restricted runtime credentials, run `test:rls:isolated` and optionally `test:rls:live` with safe test settings. Do not grant BYPASSRLS. Production tests require dedicated disposable tenants and permission to write fixtures.
- Node engine/EPERM: `node --version`, `where.exe node`; stop tsx/Vite/esbuild users before reinstall. Do not start by deleting lockfiles or elevating the app.
- Missing Python dependency: use the same `.venv` interpreter that the launcher uses. Insights and store requirements do not install the full scraper/model toolchain.
- Redis pending/dead jobs: see Workers. A three-attempt dead letter requires diagnosing the recorded error, fixing it and issuing a new authorized retry.
- Browser CORS/API error: frontend uses localhost:5000 by default; backend origin list must match the Vite URL exactly. Vite env changes need a restart/rebuild.
- Duplicate store processes: stop the extra terminal. Interleaved page logs are not by themselves proof of duplicated records; validate stable IDs and counts after a repeat sync.

## Tests and deployment

From root run `npm.cmd run build` and `npm.cmd run verify:handoff`. Before `npm.cmd run test:merge`, install the collector Python requirements and set `$env:KEEL_TEST_PYTHON = (Resolve-Path .\ai\.venv\Scripts\python.exe).Path`; the market tests launch Python separately. `npm.cmd run test:handoff` checks the new setup guards and compatibility-role migration replay in an isolated database. Backend has narrowly scoped store, market, RLS, RAG, notification and contract suites; inspect `backend/package.json` before running live suites because some require secrets and write test fixtures. Frontend `test:i18n:render` and `test:sales-import` complement static translation checks. Python connector tests are isolated; production models/providers and browser flows need their own end-to-end checks.

Build Node/frontend artifacts in CI, run Prisma migrate deploy once under an administrator deployment job, then use restricted runtime accounts. Serve frontend `dist` with an SPA fallback and HTTPS, reverse proxy API routes, set exact CORS/frontend/callback origins, retain encryption keys and back up PostgreSQL plus document/object storage. Separate process supervisors are required for each worker. Configure a stable domain/tunnel for OAuth and store testing. Root Compose is development infrastructure and does not supply TLS, backups, secret management or a complete production deployment.
