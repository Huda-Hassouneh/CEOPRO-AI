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

**Historical limitation at `d73cb4c` (superseded by the restricted reconciliation verification below):** Checkout/session setup and trials were verified offline. Real Stripe operations were forbidden for this task. Full signed-webhook activation and credit settlement under the restricted local launcher remain unverified/unprovisioned where they still need the legacy trusted authority. Do not describe this fix as a complete paid-flow certification, and do not submit a test payment merely to discover those permissions.

## Rollout boundary

No `E:` source/configuration/database/service update or restart was performed. Review the scope above before applying this commit there. A later authorized rollout should first verify that checkout is clean and owned, fast-forward only, apply the forward migrations through its own existing tooling, and restart only its positively identified owned API. Never pass the migration administrator into that process. No push/deployment occurred.


## Restricted reconciliation continuation ? 2026-10-27

Base: `d73cb4c0e2ce000d18f97ba0191f720600639398`. This continuation changes database
capabilities and recovery tooling, preserving Stripe state transitions, Custom quote
validation, catalog snapshots, credit formulas and accounting/idempotency rules.
No original Node/React source or AI algorithms were changed.

### Runtime authority

| Identity | Allowed capability | Explicitly excluded |
|---|---|---|
| `ceopro_app` | Existing tenant/auth API and worker queries under existing RLS | Webhook evidence, payment activation, direct credit grants |
| `ceopro_billing_setup` | Tenant-bound Checkout/customer reservation, unpaid promotion coordination; execute trial and schedule commands | Payment receipts, paid activation, subscription status/plan mutation, credit writes |
| `ceopro_billing_webhook` | Event-bound receipt; tenant-bound subscription/payment reconciliation, frozen Custom contract/allowance activation and promotion outcome audit | Credit ledger/balance writes, policy/rate/catalog administration, quote approval |
| `ceopro_credit_accounting` | Tenant-bound usage reservations, settlement, reconciliation, counters and request-key recovery | Subscription/payment/assignment/contract/allowance mutation; administrative credit adjustments |
| `ceopro_trial_issuer` (NOLOGIN) | Existing execute-only bounded trial issuance | Runtime login, paid activation |
| `ceopro_billing_lookup` (NOLOGIN) | Exact provider-reference routing, global spend aggregate and expired-reservation tenant discovery | Runtime login, writes, row-data disclosure through functions |
| `ceopro_schedule_writer` (NOLOGIN) | Validated schedule bookkeeping and membership row locking through fixed functions | Runtime login; changing active plan/status; arbitrary membership changes through a callable function |

All identities are non-superuser/non-BYPASSRLS/non-CREATEDB/non-CREATEROLE,
NOINHERIT/NOREPLICATION, without role memberships, table/schema/database ownership
or persistent DDL privileges. No API process receives the migration administrator
DSN. The local launcher gives all three service passwords only to the API;
workers get accounting only; frontend gets none.

Webhook scope is acquired only after the real Stripe SDK validates the raw body
signature. A connection starts without a finance tenant; it must claim its event
receipt, resolve the tenant using existing provider correlation and freshly fetched
provider state, and bind the receipt. RLS requires the same pending event and tenant.
Completed receipts cannot be reopened or rebound by this role. Payment rows must
match the invoice ID/type in that receipt. Checkout setup cannot insert receipts or
payments. Existing Custom activation still requires a paid invoice matching the
accepted immutable quote; subscription creation or acceptance alone grants nothing.

Accounting reads existing period-specific rights and updates usage, not plan grants.
Budgets remain derived from plan/contract limits. New billing periods use separate
balance keys; no webhook independently mints a second budget. Expiry recovery claims
due tenants through a bounded lookup and settles each tenant separately. Global
provider caps use an aggregate-only lookup so RLS cannot accidentally turn a global
cap into a per-tenant cap.

### Forward-only migration history

- `20261113000000_billing_reconciliation_roles.sql`: separate roles, column grants,
  receipt/tenant RLS, reference/aggregate lookups and schedule command.
- `20261113000100_billing_context_guards.sql`: actor-validated membership row-lock
  command; immutable event tenant/completion binding.
- `20261113000200_billing_principal_execute.sql`: existing active-principal predicate
  execution for the NOLOGIN guard owner only.
- `20261113000300_accounting_counter_timestamp.sql`: permit the canonical counter
  upsert's existing explicit audit timestamp insertion.

Each follow-up was added after the preceding migration had been applied to disposable
verification databases. Applied files were not rewritten. FORCE RLS and the original
three documented non-FORCE exceptions remain unchanged.

### SECURITY DEFINER review

The five new definer functions have `search_path=pg_catalog,public,pg_temp`, explicit
schema-qualified table/function references, no dynamic caller SQL, no PUBLIC EXECUTE,
and NOLOGIN/non-bypass owners. Routing checks the webhook session identity and accepts
only fixed reference kinds. Spend/expiry functions deliberately return aggregates or
tenant IDs solely to accounting. Schedule and membership-lock commands validate the
current tenant/actor using the existing active-principal authority. Their owners have
only the exact read/column permissions needed. The receipt guard and event scope
function are SECURITY INVOKER, with no elevation. Native tests inspect these ACLs.

### Collected verification

- `dev.ps1 doctor`: recovered current source/dependency identity after reboot.
- 47 tooling/recovery tests passed, including paths with spaces, child exit codes,
  read-only virtualenv reuse, credential separation and separate test Mailpit.
- **311 backend/native tests passed, zero failed/skipped**. Evidence:
  `.dev/evidence/tests/2287243362af/backend.xml` and `backend.log`.
- The new 17 native cases use actual password-authenticated service/tenant sockets,
  actual FastAPI billing routes and Stripe SDK signature checks; any attempted
  `db.system_connection()` in those runtime cases fails the test. External Stripe
  responses are labeled offline doubles, not provider acceptance.
- Covered trial/Checkout reservation/customer mapping and reuse; signed fixed/Custom
  activation; bad/unsigned signatures; replay/out-of-order reconciliation; failure,
  recovery, renewal/cancellation; frozen 13 Custom allowances/module issuance; Data/AI
  reservations/settlement; concurrency; expiry/reconciliation/idempotency; request
  refund/replay protection; cross-tenant filtering and forbidden grants/role changes.
- Fresh **144 migrations** and repeat no-op passed. Retained original **140 ? 144**
  upgrade passed with prior migration entries and checked record counts unchanged:
  `.dev/evidence/reconciliation-upgrade/`.
- An initial recovery run had 15 billing tests skipped because the generic runner
  omitted its guard. This defect was corrected (explicit safe test DSN and opt-in,
  compatible test DB name). The 311-test result above contains no skipped tests.

- Repository browser run `.dev/evidence/tests/fa220762db62/` passed: valid signup/onboarding
  fixture, API PostgreSQL/Redis readiness and exact CORS, production frontend build,
  27/27 screens each in English desktop, Arabic mobile and dark mobile, Tenant Owner
  denial of Platform Owner access, and English/Arabic assistant-evidence checks.
  API used restricted credentials; test mail/storage/Redis were separate from dev.
  Accessibility-only and full model suites were not rerun: no UI/model behavior changed.

The E: rollout must verify clean fast-forward ancestry, checkout/container/process
ownership, preserved private configuration and data, forward migrations and actual
readiness. Machine-specific rollout evidence belongs in private `.dev/evidence/`,
not a tracked secrets/configuration dump. The delivery response records the actual
rollout result. Until that operation finishes, isolated verification is the evidence
above. Real Stripe Checkout payment with these identities remains a separate gate;
o external financial resources or paid rights in development data are created by
these offline proofs. Missing or legacy manual-deployment service configuration is
not permission to substitute an administrator DSN.
