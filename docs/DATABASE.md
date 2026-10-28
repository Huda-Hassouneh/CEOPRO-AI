# Database development

## Identity and initialization

Each checkout owns `keel_dev_<random-id>` in a dedicated PostgreSQL 17/pgvector container. Only loopback ports are published. Admin credentials, restricted app password and project identity are generated once in private `.dev/config.json`.

`up` creates the initial database through the PostgreSQL image's standard initialization, then invokes the existing `backend/scripts/apply_migrations.py`. The runner applies `Final_schema.sql` once and tracks ordered files from `src/infrastructure/database/migrations/` in `schema_migrations`.

Do not use older `init_schema.sql` or Node/Prisma initialization for the unified application. Never edit applied migration history to reconcile a schema conflict.

## Approved AI provider pricing catalog

Provider prices reuse the existing **installation migrations**, not an API
lifespan hook, remote pricing fetch or second catalog service. The existing
feature/plan catalog is initialized by `20261007000000_add_usage_plans.sql`,
aligned by `20261012000000_align_plans_with_catalog.sql`, and extended by
`20261020000000_keel_subscriptions_and_credits.sql`. Subscription prices are
stored separately in `billing_plan_prices`; Stripe publication is a separate
operator action (`scripts/stripe_sync_catalog.py`), never part of this bootstrap.

The first approved AI catalog is
`20261115000000_approved_ai_provider_pricing_v1.sql`, version
`ai-provider-pricing-v1`. Approval was supplied by the project owner on
**2026-10-28**; the migration filename follows existing migration ordering,
not the approval date. It records these exact USD provider costs:

| Provider | Model | Unit | USD per million | Stored USD per token |
|---|---|---|---:|---:|
| Groq | `openai/gpt-oss-20b` | `input_token` | 0.075 | 0.000000075 |
| Groq | `openai/gpt-oss-20b` | `output_token` | 0.30 | 0.00000030 |

The public provenance URL is recorded in the migration; installation performs
no provider calls. Approval is a versioned repository decision, not a claim
that startup fetched current prices or verified an invoice.

Supported installation paths all reach `scripts/apply_migrations.py`:

- Native development: `dev.ps1 up` (or `bash dev.sh up`) starts owned
  infrastructure, applies migrations, checks the DB, then starts services.
  `dev.ps1 migrate` applies pending migrations explicitly.
- Compose installation: `backend/docker-compose.yml` has the one-shot
  `migrate` service invoking the same runner. Use the documented
  `docker compose run --rm migrate`; do not reuse a stale migration container.
- Container/PaaS installation: `backend/Dockerfile.ai` includes the schema,
  migrations and runner; `backend/docker-entrypoint.sh` runs it before Uvicorn
  and exits on migration failure. The existing staging Blueprint uses this image.

The installer uses the existing schema/migration authority. No Platform Owner
login, JWT, provider key or new bootstrap runtime permission is required.
Keep migration credentials out of restricted application/worker processes;
this change does not redesign the older deployment credential topology.

For each approved entry, the migration serializes schedule writes and either
inserts a missing schedule, fills the **exact untouched NULL Groq placeholder**
from `20261028000000_seed_unpriced_groq_rows.sql`, or preserves the entire
existing row. A non-NULL price (including explicit zero), changed source,
configurer, verification date, margin or failure/finality policy is preserved.
An owner's deliberate unpriced row is not treated as a bootstrap placeholder.
Existing configured rates do not have to equal the bundled defaults.

Each outcome is recorded atomically in append-only `entitlement_audit_log`:
action `provider_pricing_bootstrap`, `contract_ref` equal to the catalog
version, subject `ai:<provider>:<model>:<unit>`, full old/resulting schedule,
approved default, provenance, approval date and installer database identity.
The approval identity is explicitly a repository-approved catalog, not a
fabricated Platform Owner account. `schema_migrations` records installation.
An audit receipt also makes direct SQL replay a no-op after later owner edits.
Missing/deleted rows are not silently recreated after that version was applied.

`provider_cost_schedules` remains the existing mutable operational schedule;
historical catalog versions live in immutable migration files and append-only
audit receipts. Later catalog versions preserve earlier configured schedules;
they **do not automatically reprice an installation**. Existing owner commands
remain responsible for intentional rate changes and their own authorization/audit.
Ledger costs, custom pricing rate versions, subscription prices, customer
allowances, credit conversion policy and spending controls are untouched.
Unknown or deliberately unpriced units still fail with `COST_NOT_CONFIGURED`.

### Adding a future approved model rate

1. Obtain explicit approval for provider/model identifiers, billable units,
   currency, exact amounts, source and approval date. Credentials/configuration
   alone are not approval. Do not infer prices or use zero for missing values.
2. Add a **new forward-only SQL migration** after the current migration tail,
   with a new unique catalog version. Follow v1's installation/audit pattern;
   use exact NUMERIC arithmetic to convert per-million prices to per-token USD.
   Record the new approval and correct source for each model. Never edit v1
   or reuse its version/audit identity. The Groq placeholder condition is
   specific to that historical migration: do not generalize it to all NULLs.
3. New provider/model rows can be inserted; existing configured rows must be
   preserved and the outcome audited. An approved change to an already priced
   model requires a separate explicit owner rate-change operation, not a
   bootstrap overwrite. Retain all prior migration and audit versions.
4. Extend the native regressions with the new approved entries, preservation,
   replay and restricted-role cases. Run from the root:

   ```powershell
   .\dev.ps1 test --suite backend --pytest-args src/ai/tests/test_provider_pricing_bootstrap_integration_db.py -q
   ```

   This creates fresh disposable databases (including pre-upgrade and full
   installation rehearsals), retains their names in pytest evidence and makes
   no provider calls. Never target a customer/demo DB for these tests.

Verification on 2026-10-28: **PASS, 59 backend tests and 52 tooling tests**
(17 catalog regressions plus existing Credits/accounting and migration-name tests);
fresh/repeated runner installation, missing/placeholder rows, exact USD math,
owner zero/custom/NULL preservation, later-version history, populated historical
cost ledger and financial/catalog preservation, restricted-role write denials,
unchanged ACL/RLS and fail-closed unknown models. Isolated evidence:
`.dev/evidence/tests/1d6605d2d9a2/` (`backend.log`, `backend.xml`, `migrations.log`,
`run.json`); standalone catalog evidence: `.dev/evidence/tests/9581ff269fc5/`.
The combined backend command selected the catalog module above plus
`src/ai/tests/test_credits_integration_db.py` and
`src/ai/tests/test_migration_filenames.py`. No normal database migration, subscription
change, paid AI call, restart or deployment was performed. Production container
entrypoints were traced in source; no production deployment was exercised.

## Credentials and roles

| Credential | Used by | Scope |
|---|---|---|
| `keel_dev_admin` | Initial database image setup, migration/check/test commands | This checkout's isolated cluster; administrative DDL |
| `ceopro_app` + generated `APP_DB_PASSWORD` | FastAPI and all locally launched workers | Restricted, no superuser/BYPASSRLS/role or DB creation |
| `ceopro_billing_setup` + generated `BILLING_SETUP_DB_PASSWORD` | Request-bound Checkout setup/trial command | Non-superuser, no BYPASSRLS/DDL/role memberships; scoped coordination writes, no paid activation |
| `ceopro_trial_issuer` (NOLOGIN) | Owner of the one-time trial SQL command | Catalog reads and trial-only inserts; no assignment update/delete or paid activation |
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

### Checkout setup boundary

`db.billing_setup_connection(tenant_id, user_id)` reuses transaction-local context and re-applies it after commits/rollbacks. The setup credential goes only to the API and the short-lived migration provisioner. Workers and frontend keep their existing restricted credentials. `up` provisions it without replacing existing secrets; `db-check` checks role attributes and password login.

The setup role maintains Checkout attempts, Stripe customer references, unpaid promotion reservations and their coordination audit. It cannot settle payments/redemptions or write subscriptions, credit balances or plan assignments directly. One-time trials use an execute-only function owned by `ceopro_trial_issuer`, with existing eligibility rules and catalog snapshot triggers.

**This does not authorize every `db.system_connection()` caller.** Signed-payment reconciliation, credit accounting, owner maintenance and other trusted paths retain their existing configuration. The restricted local launcher is not proof that those global operations work. Do not put a migration administrator into the API to bypass errors. See [the privilege review](CHECKOUT_DATABASE_PRIVILEGE_REVIEW.md) for the exact tested scope and remaining boundary.


## Fixtures and recovery

`seed` generates synthetic business import files under `.dev/fixtures/quickstart`. Load selected files through normal authenticated import/review endpoints after signup/OTP. No provider costs, binding offers or paid subscriptions are seeded.

Fresh database tests retain their generated DBs and names for diagnosis. There is intentionally no implicit cleanup/reset command. If manually removing disposable resources, first inspect their project/root labels and generated names. Never run `docker compose down -v` against an unidentified project.

Backup your local data before intentionally removing a development volume. Keep backups outside Git. Changing a generated password without coordinating the existing cluster can break login; setup never rotates populated configuration automatically.

## Existing owner-bypass exceptions

The original entitlement-version migration explicitly uses NO FORCE for entitlement_version_state and entitlement_catalog_version so owner-run trigger functions can maintain versions. The original image job migration enables RLS without FORCE for its SECURITY DEFINER claim path. These are not application-role bypasses: ceopro_app neither owns those tables nor has BYPASSRLS/superuser.

Startup verifies these three exact existing exceptions still have policies and a separate owner, and rejects any other non-FORCE RLS table. It verifies FORCE on the other RLS tables without rewriting the original security architecture.

## Recoverable CI-style suites

`test --suite backend`, `browser-ci` and `a11y` create a fresh test database and use separate tmpfs Redis/MinIO services in the same checkout-owned Compose project. Running test APIs keep restricted credentials; only explicit migration/native-fixture setup uses the test admin. `test-cleanup` removes only those two disposable containers; databases/evidence and normal volumes are retained. See [Test environment recovery](TEST_ENVIRONMENT_RECOVERY.md) for exact commands and limits.
