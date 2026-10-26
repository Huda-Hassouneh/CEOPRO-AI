# Database development

## Identity and initialization

Each checkout owns `keel_dev_<random-id>` in a dedicated PostgreSQL 17/pgvector container. Only loopback ports are published. Admin credentials, restricted app password and project identity are generated once in private `.dev/config.json`.

`up` creates the initial database through the PostgreSQL image's standard initialization, then invokes the existing `backend/scripts/apply_migrations.py`. The runner applies `Final_schema.sql` once and tracks ordered files from `src/infrastructure/database/migrations/` in `schema_migrations`.

Do not use older `init_schema.sql` or Node/Prisma initialization for the unified application. Never edit applied migration history to reconcile a schema conflict.

## Credentials and roles

| Credential | Used by | Scope |
|---|---|---|
| `keel_dev_admin` | Initial database image setup, migration/check/test commands | This checkout's isolated cluster; administrative DDL |
| `ceopro_app` + generated `APP_DB_PASSWORD` | FastAPI and all locally launched workers | Restricted, no superuser/BYPASSRLS/role or DB creation |
| Test admin DSN | Explicit `test --suite database` only | Separately generated disposable DB in this cluster |
| Worker `SCRAPER_DATABASE_URL` | Existing worker data access | Same restricted role; existing service actor and tenant context |

Administrative credentials are not passed to API or worker processes. The application reuses `db.app_role_connection`, `db.system_connection` and the existing tenant connection pool/security functions. Never solve a permissions error by making ceopro_app a superuser.

## Commands

- `dev.ps1 infra`: start only owned PostgreSQL/Redis/storage/mail. PostgreSQL creates the named development database on first volume initialization; it never resets an existing DB. Then use `migrate` separately. `up` combines these steps with the application.

- `dev.ps1 migrate`: apply pending migrations. Failure is fatal; it is never downgraded to a warning.
- `dev.ps1 db-status`: report applied/pending registry files.
- `dev.ps1 db-check`: identity, vector extension, migration coverage, restricted password login and FORCE RLS checks.
- `dev.ps1 test --suite database`: fresh and repeat-run migrations plus existing PostgreSQL RLS tests in a new test DB.
- `dev.ps1 down`: stops services without removing volumes.

The corresponding `bash dev.sh` commands are identical.

## Isolation and transactions

Requests authenticate a real user, resolve tenant membership and permissions, then use transaction-local tenant/user context. The pooled wrapper restores that context after commits/rollbacks. Tenant foreign keys, RLS and authorized SQL functions protect canonical records and financial state.

Global owner administration uses existing platform authorization and approved database functions; Tenant Owner and Platform Owner are different roles.

## Fixtures and recovery

`seed` generates synthetic business import files under `.dev/fixtures/quickstart`. Load selected files through normal authenticated import/review endpoints after signup/OTP. No provider costs, binding offers or paid subscriptions are seeded.

Fresh database tests retain their generated DBs and names for diagnosis. There is intentionally no implicit cleanup/reset command. If manually removing disposable resources, first inspect their project/root labels and generated names. Never run `docker compose down -v` against an unidentified project.

Backup your local data before intentionally removing a development volume. Keep backups outside Git. Changing a generated password without coordinating the existing cluster can break login; setup never rotates populated configuration automatically.

## Existing owner-bypass exceptions

The original entitlement-version migration explicitly uses NO FORCE for entitlement_version_state and entitlement_catalog_version so owner-run trigger functions can maintain versions. The original image job migration enables RLS without FORCE for its SECURITY DEFINER claim path. These are not application-role bypasses: ceopro_app neither owns those tables nor has BYPASSRLS/superuser.

Startup verifies these three exact existing exceptions still have policies and a separate owner, and rejects any other non-FORCE RLS table. It verifies FORCE on the other RLS tables without rewriting the original security architecture.
