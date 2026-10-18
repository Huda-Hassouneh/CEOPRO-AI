# KEEL

> **18 October review update:** the custom competitor bridge and dependent Smart Alerts UI are suspended. The current team competitor source is restored unchanged. Earlier descriptions of active custom tracking below are historical. See [current review instructions](docs/COMPETITOR_REVIEW.md).


KEEL brings a merchant's catalog, recorded sales and market observations into one tenant-scoped workspace. A retailer can connect a WooCommerce or Shopify store, inspect sales and stock, forecast individual products, compare confirmed competitor matches and ask questions about uploaded business documents. Platform staff manage plans and access separately from merchant accounts.

The application is React/Vite → Express/Prisma → PostgreSQL. Python supplies store adapters, market collectors and analytical services. Node owns authentication, permissions, subscriptions, source approval and canonical writes. This repository includes older standalone Python application and deployment code; those are not an alternative startup procedure for the React application.

## Start here

- [Development setup](docs/DEVELOPMENT.md): fresh database, existing database, daily restart and Windows terminals.
- [Worker reference](docs/WORKERS.md): every consumer, scheduler, retry and legacy process.
- [Integrations](docs/INTEGRATIONS.md): Shopify, WooCommerce, Stripe, discovery and model providers.
- [Environment reference](docs/ENVIRONMENT.md): variables, consumers and optional/legacy settings.
- [Architecture](docs/ARCHITECTURE.md), [feature status](docs/FEATURES.md), [AI comparison](docs/AI_EVOLUTION.md).
- [Handoff results](docs/HANDOFF_REPORT.md): changes, executed checks and remaining blockers.
- [Security](SECURITY.md) and [contributing](CONTRIBUTING.md).

## Repository

| Directory | Contents |
|---|---|
| `frontend/` | React application, English/Arabic dictionaries, shared UI and browser tests |
| `backend/` | Express modules, Prisma schema/migrations, Node workers and restricted-role tests |
| `ai/` | Python adapters, insights API, market collectors, model pipelines and standalone legacy API |
| `scripts/` | Cross-platform launchers and guarded development database setup |
| `docs/` | Authoritative operational guides and machine-readable audit tables |
| `reference/` | Historical Python deployment/frontend examples; excluded from normal startup |
| `design/liquid-glass/` | Independent design reference assets |
| `searxng-config/` | Optional search-service configuration |

## Prerequisites and installation

Use Node 24 LTS (`.nvmrc`; package engines now require 24), npm with the supplied lockfiles, Python with `venv` (the supplied Python images use 3.11; isolated checks used 3.12), Docker and Docker Compose v2. PostgreSQL 17 with pgvector and Redis 7 are supplied by the root Compose file. Model dependencies are unpinned/ranged Python requirements, so a new Python resolution is not a reproducible lockfile install. No GPU is needed for the store adapter or insights API.

```powershell
git clone <repository-url>
cd <repository-directory>
npm.cmd run setup
# Fill the four .env files from their examples before continuing.
docker compose up -d
# NEW, EMPTY KEEL_DEV only:
npm.cmd run db:init
npm.cmd run db:roles
npm.cmd run setup:store
```

For an existing migrated database use `npm.cmd run db:migrate`, not `db:init`. Migration and password setup use a separate administrative URL; the application's URL remains `ceopro_app`. Never reset migrations or delete volumes to fix credentials. Follow [Development](docs/DEVELOPMENT.md) for administrator provisioning and first-owner/catalog setup before signing up and purchasing a plan.

## Processes

Run each long-lived command in a separate terminal, from the repository root. Start PostgreSQL/Redis first, then APIs, workers and the frontend. Only start the services used by your workflow.

| Service | Purpose | Local port | Dependencies | Command |
|---|---|---|---|---|
| PostgreSQL | Canonical data and RLS | 5433 | Docker | `docker compose up -d` |
| Redis | Market event streams | 6379 | Docker | same Compose command |
| Backend | Auth, billing, tenant API | 5000 | Migrated DB, runtime credentials | `npm.cmd run dev:backend` |
| Frontend | Merchant/platform UI | 5173 | Backend | `npm.cmd run dev:frontend` |
| Store adapter | Stateless WooCommerce/Shopify API translation | 8002 | Python, shared service secret, reachable store | `npm.cmd run api:store` |
| Store sync | Scheduled canonical product/order/stock/invoice imports | none | DB app+dispatcher roles, adapter | `npm.cmd run worker:store-sync` |
| Insights API | Business recommendations with recorded evidence | 8001 | Python insights requirements, DB, shared JWT secret | `npm.cmd run api:insights` |
| Market dispatcher | Approved schedule/outbox → Redis | none | Dedicated DB role, Redis, cost-guard Python | `npm.cmd run worker:dispatch` |
| Market supervisor | Price, review analysis and discovery consumers | optional metrics | DB actor, Redis, Python collector dependencies | `npm.cmd run workers:market` |
| File ingestion | Staging → canonical imports | none | Dedicated ingestion DB role | `npm.cmd run worker:ingestion` |
| Platform notifications | Platform outbox delivery | none | Dedicated notification DB role | `npm.cmd run worker:platform-notifications` |
| Tenant notifications | Tenant outbox delivery | none | Same notification role | `npm.cmd run worker:tenant-notifications` |

Hosted Gradio model endpoints are separate dependencies for the current Node AI clients; starting the local store or insights API does not replace them. See the integration guide. Implemented code does not mean a live third-party account was verified during this handoff.

## Frequent problems

- `28P01`: inspect host/port/role (without printing passwords). Use the root Compose project, not `backend/docker-compose.yaml`. On the intended DEV database run `db:roles` after configuring all four runtime URLs.
- Database host `lo`: repair the malformed URL in `backend/.env`; store sync also uses `MARKET_DISPATCHER_DATABASE_URL`.
- `EPERM` unlinking `esbuild.exe`: stop the backend/frontend/watch processes using that dependency tree before `npm ci`; check the installed Node version with `where.exe node`.
- `EADDRINUSE`/Windows 10048: one API already owns that port; reuse it or stop that specific process.
- Browser API/CORS failure: match `VITE_API_BASE_URL`, backend `CORS_ORIGINS` and the actual frontend origin, then restart Vite.
- Shopify redirect or order permission error: exact callback whitelist and protected order-data approval are separate requirements.
- Cloudflare 1033/NXDOMAIN: restart the appropriate tunnel and update its consumers; temporary hostnames are not stable store identities.
- Pending market collection: Node's dispatcher publishes work; Python consumers collect it. Check both and the durable job/dead stream, not only a Submitted badge.

This handoff does not establish production readiness. See the validation report for fresh-install restrictions and live checks still required.
