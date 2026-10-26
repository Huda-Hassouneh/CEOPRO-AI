# Local development

## First run

Install Git, CPython 3.11/3.12 (64-bit), Node 24 LTS and Docker Desktop with Linux containers. Run `python --version`, `node --version`, `docker info` and `docker compose version`.

From the checkout root:

```powershell
.\dev.ps1 setup
.\dev.ps1 up
```

Use `bash dev.sh` instead of `.\dev.ps1` on Linux/macOS. The same Python orchestrator handles both; Linux/macOS execution status is recorded in the verification report.

Setup checks prerequisites before installing, creates its own `.dev/venv` and uses the repository dependency constraints. It uses `npm ci`, never an undeclared shared node_modules directory. Dependency fingerprints make repeated setup inexpensive. If you deliberately remove packages from an existing venv, remove only `.dev/dependencies.json` to request dependency reinstallation; do not delete configuration or volumes.

Setup does not start application processes or populate a database. `up` starts infrastructure, runs forward migrations, verifies pgvector/restricted login/FORCE RLS, starts API/workers, verifies readiness, then starts Vite and checks its actual API proxy.

## Modes and ownership

- `up` defaults to **full**: all eight supported workers.
- `up --mode core`: forecast, image and connector workers.
- `restart` keeps the last successful mode.
- Stop before changing mode: `down`, then `up --mode full`.

Each checkout receives a random Compose project ID, labeled containers/volumes, a dedicated DB and Redis instance. Ports bind to loopback and are selected once from available defaults. No existing API, DB, Redis or runtime is adopted. Native worker metrics use their existing binding behavior; avoid exposing development hosts to untrusted networks.

Python/Node processes record PID, creation time, executable and exact command line. Shutdown refuses identity mismatches. Infrastructure operations verify the checkout labels. A launch failure leaves evidence/resources for diagnosis; `down` safely stops owned resources while preserving data. There is no automatic volume removal or database reset.

Only one mutating developer command runs at a time. If interrupted, inspect `.dev/command.lock` and its PID before removing a proven stale lock.

## Commands

```powershell
.\dev.ps1 status
.\dev.ps1 doctor
.\dev.ps1 logs --tail 80
.\dev.ps1 logs --service connectors --follow
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

`setup --models` installs the existing AI requirements. Tesseract OCR and optional browser-assisted scraping need OS binaries; see integrations. No setup command inserts provider cost schedules or commercial pricing.

## Existing workflows

`backend/docker-compose.yml` remains the legacy/Codespaces deployment topology, including telemetry and local LLM options. Its fixed container names/ports make it unsafe for parallel checkouts. The new command generates only a small isolated infra Compose file from the same service technologies and reuses the existing MinIO Dockerfile and migration/worker entry points. Do not mix its volumes with the new project.

`tools/keel-verification/` remains the specialist synthetic acceptance harness. Its reset commands are intentionally excluded from everyday development.
