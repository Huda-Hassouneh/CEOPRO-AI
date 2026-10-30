# KEEL — AI-Powered Business Intelligence Platform

KEEL helps small and growing businesses understand sales, manage stock and
compare market evidence before making operating decisions. Customers bring
their products, invoices, inventory and business documents; KEEL turns that
data into dashboards, forecasts, pricing guidance and cited answers.

The application supports English and Arabic, including right-to-left layouts.
One Python backend owns authentication, tenant isolation, subscriptions and
usage accounting. A React application serves customers and Platform Owners.

## Features at a glance

| Feature | What customers can do |
|---|---|
| Dashboard analytics | Explore sales, stock and performance over time. |
| Product management | Maintain a bilingual catalog with prices and costs. |
| Inventory management | Track balances, low stock and replenishment needs. |
| Data connections and extraction | Upload business files, review extracted data and confirm imports. |
| Demand prediction | Estimate future demand from actual sales history. |
| Competitor management | Maintain competitors and dated price observations. |
| Market intelligence and perception | Review market evidence and customer sentiment when sufficient data exists. |
| Pricing recommendations | Compare products and inspect evidence behind proposed prices. |
| Assistant and knowledge base | Ask questions grounded in business data and uploaded documents, with citations. |
| Alerts and notifications | Surface stock risks and deliver configured notification digests. |
| Marketing copy and images | Generate drafts and visual assets through configured AI providers. |
| Billing and subscriptions | Manage plans, trial access, allowances and Data/AI Credits. |
| Shopify and WooCommerce | Connect authorized stores and review synchronized provider data. |
| Reports and exports | Inspect sales and financial summaries; export supported report formats. |
| Platform administration | Let authorized platform staff administer the service separately from tenant owners. |

These workflows exist in source; they do not all have full production or live-provider
acceptance. Hosted AI, scraping, merchant stores, payments and some local models
need additional configuration. See [feature implementation and limitations](docs/FEATURES.md).

## Quick start

Install Git, **64-bit CPython 3.11 or 3.12**, **Node 24 with npm**
(the launcher accepts Node 22.12+) and **Docker Desktop with Linux containers
and Compose 2.20+**. Windows PowerShell 5.1+ is the verified native workflow.

After obtaining the team's repository and checking out the intended development
branch, open a terminal at its root:

```powershell
.\dev.ps1 setup
.\dev.ps1 up --mode full
.\dev.ps1 status
```

No environment-file copy or provider account is required for the core stack.
Setup installs this checkout's dependencies and generates private local
credentials. Startup creates isolated infrastructure, applies migrations and
launches the API, frontend and eight workers. It does not seed business data.

**Open the frontend and Mailpit URLs printed by `up`.** Sign up, read the
verification email in Mailpit, and complete onboarding. No shared password,
demo account or Platform Owner is created automatically.

[Detailed setup and first-login checklist](docs/LOCAL_DEVELOPMENT.md) explains
requirements, expected results and safe stop/restart. The Bash entry point
`bash dev.sh` uses the same orchestrator; Linux/macOS execution is not certified
by the Windows onboarding verification.

## What do you want to do?

| Task | Guide |
|---|---|
| Run KEEL locally | [Setup and daily development](docs/LOCAL_DEVELOPMENT.md) |
| Understand the system | [Architecture](docs/ARCHITECTURE.md) |
| Find a feature's source and tests | [Feature guide](docs/FEATURES.md) |
| Develop backend functionality | [Python backend](backend/README.md) |
| Develop frontend functionality | [React frontend](frontend/README.md) |
| Work with the database or approved catalogs | [Database and migrations](docs/DATABASE.md) |
| Work on AI features | [AI workflows](docs/FEATURES.md#ai-workflows) and [provider setup](docs/INTEGRATIONS.md#ai-and-market-providers) |
| Configure integrations or environment variables | [Integrations](docs/INTEGRATIONS.md) · [Configuration](docs/ENVIRONMENT_VARIABLES.md) |
| Start or debug background work | [Workers](docs/WORKERS.md) |
| Run tests | [Testing](docs/TESTING.md) |
| Diagnose a failure | [Troubleshooting](docs/TROUBLESHOOTING.md) |

## Technology and source layout

React **19** / Vite **8**, React Router, TanStack Query and Zustand communicate
with FastAPI. PostgreSQL **17** with pgvector stores tenant data; Redis **7**
supports queues, caching and rate limits; MinIO stores files and assets.
Python workers run forecasts, image jobs, market collection and commerce sync.
Stripe and hosted AI/search/merchant providers are optional integrations.
Dependencies are declared in the Python requirements files and the frontend
package manifest/lockfile; setup derives its Python constraints from those files.

```text
frontend/src/                  React routes, feature pages, API adapters and locales
backend/src/ai/                FastAPI routers and business/AI services
backend/src/market_scraper/    Market collection, commerce adapters and workers
backend/src/infrastructure/   Database schema, migrations, storage and messaging
backend/scripts/              Migration runner and operator/test utilities
tools/dev/                    Shared developer launcher and tests
docs/                         Developer guides and retained technical evidence
```

## Local services and common commands

Preferred frontend/API URLs are `http://127.0.0.1:5173` and
`http://127.0.0.1:8000`; API docs are at the API's `/docs`. Mailpit prefers
`http://127.0.0.1:58025`, and MinIO's console prefers port `59001`.
Setup selects other free ports if needed and retains them per checkout.
Use printed URLs or `doctor`, not a teammate's remembered ports.

| Action | Command |
|---|---|
| Start all services | `.\dev.ps1 up --mode full` |
| Stop owned services; retain data | `.\dev.ps1 down` |
| Restart using the previous mode | `.\dev.ps1 restart` |
| Check readiness / diagnose setup | `.\dev.ps1 status` / `.\dev.ps1 doctor` |
| Follow API or worker logs | `.\dev.ps1 logs --service api --follow` |
| Run offline tooling tests | `.\dev.ps1 test` |
| Run frontend tests, lint and build | `.\dev.ps1 test --suite frontend` |
| Apply pending migrations | `.\dev.ps1 migrate` |
| Inspect migration/security state | `.\dev.ps1 db-status` / `.\dev.ps1 db-check` |

Keep `.dev/` private. Optional credentials belong in `.dev/integrations.env`,
using [the safe template](tools/dev/integrations.env.example). Never place
secrets in frontend `VITE_*` settings. Approved AI provider rates initialize
through migrations; provider costs, customer Credits and plan prices remain
separate. Missing credentials or unapproved rates keep that capability unavailable.

[Documentation index](docs/README.md) separates developer guides from historical
decisions and evidence. [Contributing](docs/CONTRIBUTING.md) explains change and
test expectations. [Repository verification](docs/REPOSITORY_READINESS.md) records
the measured onboarding results and remaining PR limitations. Older Codespaces
and deployment workflows remain available for their specific environments;
do not combine them with the native launcher against the same services.
