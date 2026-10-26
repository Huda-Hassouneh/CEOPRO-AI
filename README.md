# KEEL

KEEL helps businesses use their products, sales, inventory and market evidence to make operating decisions. It combines business data management with demand forecasts, pricing recommendations, competitor monitoring, perception analysis, document-grounded assistance and reporting.

One Python/FastAPI backend owns authentication, subscriptions, entitlements, Credits and accounting. The React application serves customers and Platform Owners.

## Stack and architecture

React 19 / Vite 8 → FastAPI → PostgreSQL with pgvector and tenant RLS. Redis supports queues, caching and rate limits. MinIO stores uploads/assets. Python workers handle forecasting, images, commerce and market jobs. Stripe, merchant stores and hosted AI/search providers are optional external dependencies.

```text
frontend/       React application, API adapters, locales and tests
backend/src/ai/  FastAPI routers, domain services and AI orchestration
backend/src/market_scraper/  Collection, discovery and commerce workers
backend/src/infrastructure/ Database, security and shared infrastructure
backend/scripts/ Migration runner and operational/test utilities
tools/dev/      Shared local developer commands
docs/           Current guides and preserved integration/decision evidence
```

## Prerequisites

- Git, **64-bit CPython 3.11 or 3.12**, **Node 24 LTS** (22.12+ also supported) and npm.
- Docker Desktop/Engine running **Linux containers**, with Docker Compose 2.20+.
- Several GB of disk for Python/Node dependencies and container images. Optional model libraries/weights need substantially more memory and disk.
- Windows PowerShell 5.1+; Linux/macOS use Bash and Python 3.11/3.12.

## Quick start

From a fresh clone, select the team integration branch, then run from the repository root:

```powershell
git switch integration/keel-full-migration
.\dev.ps1 setup
.\dev.ps1 up
```

Linux/macOS equivalent: `bash dev.sh setup`, then `bash dev.sh up`.

Setup creates a private, Git-ignored `.dev/` directory, a new venv, frontend dependencies and per-checkout credentials. It does **not** load or overwrite existing `.env` files. First startup creates isolated infrastructure and applies the repository migrations.

**Open the URLs printed by `up`.** Preferred defaults are frontend http://127.0.0.1:5173 and API http://127.0.0.1:8000. Setup chooses free ports when defaults are occupied; inspect them with `doctor`. Signup verification emails appear in the printed local Mailpit inbox. No test account or Platform Owner is created automatically.

## Environment setup

Required database, Redis, JWT, vault, storage, SMTP and URL configuration is generated once in `.dev/config.json`. Keep this directory private and out of Git. Never copy it between checkouts.

Optional provider settings belong in `.dev/integrations.env`; start with [the safe example](tools/dev/integrations.env.example). Empty/missing provider credentials mean those capabilities are unavailable. Setup creates no financial rates, promotions, quotes, subscriptions or Credits.

For model-dependent development, install the existing model libraries explicitly:

```powershell
.\dev.ps1 setup --models
```

Model weights may download on first use. This does not configure hosted AI providers or their verified cost schedules.

## Daily development

| Task | Command |
|---|---|
| Start all locally supported workers, API and UI | `.\dev.ps1 up` |
| Smaller runtime: forecast, image and commerce workers | `.\dev.ps1 up --mode core` |
| Stop owned processes and containers; retain data | `.\dev.ps1 down` |
| Restart, preserving the last selected mode | `.\dev.ps1 restart` |
| Check identity/readiness | `.\dev.ps1 status` |
| Diagnose prerequisites/configuration | `.\dev.ps1 doctor` |
| Tail application logs | `.\dev.ps1 logs --service api --follow` |
| Apply pending migrations | `.\dev.ps1 migrate` |
| Migration inventory / DB security health | `.\dev.ps1 db-status` / `.\dev.ps1 db-check` |
| Generate optional synthetic import files | `.\dev.ps1 seed` |
| Tooling tests (no services) | `.\dev.ps1 test` |
| Frontend tests, lint and build | `.\dev.ps1 test --suite frontend` |
| Fresh/repeat migrations and native RLS tests in a separate test DB | `.\dev.ps1 test --suite database` |

Use `down` before switching worker modes or changing ports. `up` is repeatable. It refuses unowned listeners instead of stopping them. There is no reset/delete-data command.

## Database and sample data

[Database guide](docs/DATABASE.md) explains migration/admin versus restricted application credentials. Startup uses [scripts/apply_migrations.py](backend/scripts/apply_migrations.py); applied migration files remain immutable.

`seed` generates labeled synthetic files in `.dev/fixtures/quickstart`. It **does not load database records**. Sign up, verify your email in Mailpit, then use the application's import/review workflow. This preserves onboarding, entitlement checks and canonical data ownership.

## Workers and external integrations

The default full mode starts eight existing worker entry points. API lifespan tasks handle discovery refresh, notification digests and billing upkeep; extraction uses the existing API background-task flow. Read [WORKERS](docs/WORKERS.md) for queues, readiness and retries.

Without credentials, local navigation, authentication, data management and non-provider workflows remain usable. Hosted AI, paid search, merchant synchronization and Stripe payments need explicit test configuration; a running worker is not evidence that an external feature works. See [INTEGRATIONS](docs/INTEGRATIONS.md).

## Tests and common tasks

The command interface tests developer tooling by default. It does not run expensive billing or AI-provider acceptance suites implicitly. See [LOCAL_DEVELOPMENT](docs/LOCAL_DEVELOPMENT.md) for focused Python tests, debugging, individual processes and infrastructure logs.

## Troubleshooting and contribution

Start with `doctor`, `status` and the failed service log. [Troubleshooting](docs/TROUBLESHOOTING.md) covers Docker, ports, dependencies, migrations, email, CORS and missing providers. [Contributing](docs/CONTRIBUTING.md) explains scoped changes, tests, migrations and security boundaries.

## Documentation

[Documentation index](docs/README.md) distinguishes current contributor guidance, architecture references and historical acceptance evidence. [Architecture](docs/ARCHITECTURE.md), [backend](backend/README.md), [frontend](frontend/README.md) and [environment variables](docs/ENVIRONMENT_VARIABLES.md) are the main references.

The existing `./keel` and `.devcontainer/` workflow is retained for Codespaces compatibility. Native local development uses the commands above; do not run both launchers against the same services.
