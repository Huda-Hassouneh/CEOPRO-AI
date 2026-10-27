# Checkout database privilege review

Date: 2026-10-27. Source base: `22d6aa2113eca58708e1ae19492adca638510de4`, branch `integration/keel-full-migration`. This report belongs to the commit containing the scoped fix; obtain its hash with `git log -1 --format=%H -- docs/CHECKOUT_DATABASE_PRIVILEGE_REVIEW.md`.

## Decision

**Do not give the development API the migration administrator's DSN.** A separate non-superuser setup identity is sufficient for the observed Checkout failure and one-time trial issuance. It is not a replacement for every trusted connection in the application.

The `E:\KEEL START\CEOPRO-AI` checkout and its services were left unchanged while validating this design. No Checkout Session, customer, payment or other Stripe resource was created. Provider responses used in tests are explicitly offline fixtures.

## Actual database inspection (read-only)

The proposed DSN resolves to the dedicated development database `keel_dev_84d5954f7dfa`, role `keel_dev_admin`:

| Attribute | Observed |
|---|---|
| SUPERUSER / BYPASSRLS | Both true |
| CREATEDB / CREATEROLE | Both true |
| Database ownership / CREATE | Owner, CREATE allowed |
| Public schema | Owned by `pg_database_owner`; administrator has CREATE |
| Owned public relations | 500 (tables/indexes/other relations, not 500 tables) |
| `ceopro_app` | No superuser, BYPASSRLS, CREATEDB or CREATEROLE |
| Checkout table | RLS and FORCE RLS both enabled |
| Tenant Checkout table permissions | SELECT allowed; INSERT and UPDATE denied |
| Existing migration coverage | 138 before this fix |

No credentials or DSNs are included here. The administrator has considerably more authority than Checkout requires.

## Root cause

The launcher correctly gave API/worker processes a restricted `DATABASE_URL`. However, `db.system_connection()` uses that same URL, and request-bound billing code used it as a trusted writer. `service.create_checkout()` called `checkout_attempts.reserve()`, which attempted a prohibited INSERT into `billing_checkout_attempts`. The generic provider exception handler reported 502 even though the failing operation was PostgreSQL, before session creation. This was not a Stripe-key or CORS failure.

## New boundaries

| Identity | Permitted operations | Explicit exclusions |
|---|---|---|
| `ceopro_app` | Existing tenant-scoped operations | No new grants; Checkout writes remain denied |
| `ceopro_billing_setup` (LOGIN) | Context-bound Checkout attempts/customer references; active promotion reads, unpaid reservation/audit coordination; execute the trial command | No ownership, role memberships, persistent DDL, SUPERUSER/BYPASSRLS, payment/subscription writes, credit writes or direct plan/trial writes |
| `ceopro_trial_issuer` (NOLOGIN) | Own one fixed-path command; read eligibility evidence and insert a catalog-defined one-time trial/assignment | No login, memberships, table/schema/database ownership, assignment updates/deletes, trial deletion or paid activation |
| Migration administrator | Existing schema initialization and password provisioning | Never added to the running API, workers or frontend |

The setup connection uses the existing context wrapper: transaction-local tenant/user identity is restored after commit/rollback. RLS checks tenant identity, active principal and permitted billing membership. Historical Checkout immutability remains enforced. Promotions reuse the existing global-cap function, returning eligibility rather than another tenant's rows. Coordination events cannot impersonate signed Stripe confirmations. Trial commands reject NULL operations, require a billing role to grant, lock person and tenant, use database time/catalog duration, and preserve the existing catalog snapshot triggers.

`BILLING_SETUP_DB_PASSWORD` is generated once in private checkout configuration, passed only to API/migration provisioning, and blocked from integrations.env overrides. Ordinary tenant queries, workers and frontend retain their restricted credentials. Manually managed deployments without this variable retain their existing trusted-connection behavior for compatibility; this is not a recommendation to use an administrator at runtime.

### Forward migrations

- `20261112000000_billing_setup_service.sql`: setup identity, scoped coordination permissions, non-login trial issuer and execute-only trial command.
- `20261112000100_billing_setup_command_guards.sql`: forward-only command NULL validation, active-principal policy checks and audit-evidence restrictions.

Automatic review initially rejected a broader unproven proposal. No SQL from it was applied to existing databases. After isolated proof, the narrower solution was implemented. Review required subsequent hardening to be a separate forward migration because the first proposal had already been applied in the disposable verification database. Original 138 migrations and history records were not edited.

## Evidence

All testing used a uniquely labelled `pgvector/pgvector:pg17` container with tmpfs data, no mounted volumes, and loopback ports. Existing databases and services were not used for writes.

| Check | Actual result |
|---|---|
| Initial isolated capability proofs | 30 checks passed: Checkout/concurrency, execute-only trials, unpaid promotion coordination |
| Final native billing + existing RLS regressions | 243 passed, 0 failed, 0 skipped |
| Developer tooling | 43 passed; includes API-only credential delivery and unchanged worker/frontend identity |
| Fresh installation | 140 migrations applied |
| Original baseline upgrade | Original 138, then two new forward migrations |
| Repeat migration runs | Zero pending/applied changes |
| FORCE RLS | 120 tables; existing declared exceptions retained |
| Role password login | Actual `session_user=current_user=ceopro_billing_setup`; no admin DSN; role switching denied |
| HTTP | Actual FastAPI billing router against native PostgreSQL: durable/idempotent Checkout and one-time trial; provider calls stubbed |
| Protected env example | SHA-256 unchanged: `6850C0B739FF783FE57466C509105DB4DF3F03AED16E1D939CBA870167EF2F28` |

Native tests also deny cross-tenant inserts, non-billing/suspended principals, forged settlement/evidence, DDL and direct entitlement/credit writes; verify frozen Checkout parameters and catalog snapshots; enforce per-person trial reuse restrictions and concurrent one-time issuance.

Private logs/JUnit/ledger: `%TEMP%\KEEL\CheckoutLeastPrivilegeProof-20261027`. These historical files are not runtime prerequisites. Reproduce native coverage through the version-controlled commands:

```powershell
.\dev.ps1 test --suite tooling
.\dev.ps1 test --suite backend --pytest-args tests/billing src/ai/tests/test_rls_integration_db.py -q
```

## Remaining trusted-connection scope

The architecture does **not** require SUPERUSER or DDL for these operations, but the current implementations use a broad trusted connection. They were not silently assigned to the setup identity:

| Callers | Why they need a distinct trusted capability |
|---|---|
| `routers/billing.py:stripe_webhook` / `billing/webhooks.py` / `billing/store.py` | Record verified events, reconcile subscriptions/payments and activate frozen entitlements; customer access must never grant this capability |
| `billing/credits.py:_system_connection`, reserve/settle/reconcile/expiry | Global budget/provider controls and authoritative credit accounting |
| `routers/billing.py:change_plan`, `cancel_scheduled_change` | Store verified provider transition/schedule state |
| `routers/platform.py` trusted promotion/catalog/contract paths | Platform-authorized cross-tenant maintenance and audit; separate from Tenant Owner |
| `routers/auth.py:_seat_limit` | Read an invited workspace's rights before the invitee becomes a member |
| `routers/settings.py:delete_company` | Authorized multi-table deletion with retention/subscription guards |
| `marketing/image_worker.py` trusted job/heartbeat paths | Claim/heartbeat/reconciliation operations with worker-specific authority |

These require separately reviewed command-scoped service roles/functions, or a dedicated reconciliation process with only its required credentials. No permanent schema-owner credential was introduced as a shortcut. The setup role must not be broadened into an all-purpose financial writer.

**Release limitation:** Checkout/session setup and trials are verified offline. Real Stripe operations were forbidden for this task. Full signed-webhook activation and credit settlement under the restricted local launcher remain unverified/unprovisioned where they still need the legacy trusted authority. Do not describe this fix as a complete paid-flow certification, and do not submit a test payment merely to discover those permissions.

## Rollout boundary

No `E:` source/configuration/database/service update or restart was performed. Review the scope above before applying this commit there. A later authorized rollout should first verify that checkout is clean and owned, fast-forward only, apply the forward migrations through its own existing tooling, and restart only its positively identified owned API. Never pass the migration administrator into that process. No push/deployment occurred.
