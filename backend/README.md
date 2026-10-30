# KEEL Python backend

FastAPI is the unified application's business/API authority. Start the supported local stack from the repository root with `dev.ps1 setup`, then `dev.ps1 up`; Unix uses `bash dev.sh`. See [local development](../docs/LOCAL_DEVELOPMENT.md).

## Layout

- `src/ai/main.py`: app bootstrap, CORS, middleware, router registration and lifespan.
- `src/ai/routers/`: public HTTP contracts by domain.
- `src/ai/core/`: authentication/permissions, entitlements, usage, receipts and shared validation.
- Domain packages: services, orchestration, data access and existing model pipelines.
- `src/infrastructure/`: PostgreSQL schema/migrations, tenant connection pool, security, messaging and monitoring.
- `src/market_scraper/`: market/commerce adapters and workers.
- `scripts/apply_migrations.py`: authoritative forward migration runner.
- `tests/` and package-local `tests/`: contract, native database and unit regressions.

## API and database

The API entry point is `python -m uvicorn src.ai.main:app` from this directory, using a correctly configured environment. The root launcher supplies it and checks `/health/ready`; `/health` alone proves liveness.

Requests resolve JWT identity, active tenant membership and permissions, then use restricted ceopro_app connections. Transaction-local tenant/user context is reapplied across commits/rollbacks. Tenant isolation and Platform Owner authorization are separate safeguards. Never connect runtime services as migration administrator.

[Database guide](../docs/DATABASE.md) covers initialization, migration status, restricted credentials, FORCE RLS and isolated tests. Applied migrations are immutable.

## Domain invariants

Canonical products, inventory and invoices are updated through established services and receipts. Imports/sync stage records before approved promotion. Billing, subscriptions, entitlements, AI/Data Credits and accounting retain one Python authority. Quote approval does not activate paid rights. Provider failures must not masquerade as successful model results.

Expected domain errors use existing exception contracts and localized error handling; inspect service logs and durable job state for asynchronous failures. Do not expose DSNs, tokens or private financial configuration in error responses.

## Testing and workers

Use root `test --suite database` for a new disposable migration/RLS database, and `test --suite backend --pytest-args ...` for a focused isolated backend selection. [Testing](../docs/TESTING.md) explains dependencies, native fixtures and evidence. Do not direct mutation tests at developer/customer databases. [Worker entry points](../docs/WORKERS.md) document queues, retries and readiness.

Model libraries/weights, hosted services and cost configuration are feature prerequisites; [integrations](../docs/INTEGRATIONS.md) distinguishes them. The existing `.env.example` remains a manual/deployment reference and is not rewritten by setup.

## Historical infrastructure evidence

The previous Phase 1 infrastructure blueprint is preserved in [docs/archive/BACKEND_PHASE1_README.md](../docs/archive/BACKEND_PHASE1_README.md). It is not current startup/reset guidance.

## First identity and Platform Owner access

Use the frontend signup and verify the actual OTP in the printed Mailpit inbox. A workspace owner is a Tenant Owner, not a Platform Owner. Startup intentionally creates neither an account nor privileged membership. Platform access requires the existing authorized team/invitation or one-time operator bootstrap workflow; see scripts/bootstrap_platform_owner.py and the guarded keel_bootstrap_platform_owner SQL function. Never promote users by editing membership rows or weakening route/RLS checks. Bootstrap is an explicit operator action, not part of setup/seed, and was not exercised by this startup smoke.
