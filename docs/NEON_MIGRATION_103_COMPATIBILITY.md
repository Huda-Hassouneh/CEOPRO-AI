# Managed PostgreSQL installer compatibility

This is an installer-only correction. It does not change runtime authorization,
RLS policies, billing, or any historical SQL migration.

The consolidated follow-up below covers migrations 142, 143, 144 and 165.
Earlier test counts and cloud observations in this document retain their
original scope; the latest local remaining-sequence results are recorded there.

## Cause and correction

`20261031000000_add_durable_tenant_notifications.sql` includes `ALTER ROLE ...
NOSUPERUSER`. PostgreSQL 17 requires true SUPERUSER authority for that operation,
even when the target is already non-superuser. A Neon installation owner is not
a true superuser. PostgreSQL also requires SET permission for `OWNER TO`, and
inherited owner authority for the subsequent function ACL revocations/grants.
SET permission alone is insufficient to establish those ACLs.

The migration runner recognizes only the exact reviewed migration 103 content
(SHA-256 of newline-normalized UTF-8). It retains the original CREATE ROLE,
checks all seven restrictive role attributes, rejects outbound memberships,
unexpected incoming grantees and table/schema/database ownership, and verifies
the final definer ACLs and RLS. An unsafe existing role is rejected, not repaired.

A true superuser executes the original SQL after validation. A PostgreSQL 16+
non-superuser installer uses its existing ADMIN authority to grant itself only
temporary SET and inheritance of the restricted definer owner. The original
table/function/trigger/ACL SQL then runs unchanged. Exact prior memberships are
restored before commit. No runtime role or Neon-managed administrator is changed.
Failure rolls back the migration, including temporary permissions and role DDL.
Autocommit is rejected. Permission errors are never swallowed.

The runner records filenames, not content checksums, and commits each migration
separately. Applied files remain skipped. Historical migration SQL is unchanged;
no additional migration or history-table change is introduced.

## Focused verification

Use a dedicated, disposable local PostgreSQL 17 cluster and a
`keel_m103_test` database initialized through the original first 102 migrations.
The non-superuser installer owns that baseline and has CREATEROLE; the local
Neon-compatible test installer also has CREATEDB, REPLICATION and BYPASSRLS,
matching the observed Neon installation authority. These are installation-only
credentials, never application credentials. An extension may be preinstalled by
the local superuser to model Neon's managed extension installation.

Supply `KEEL_M103_TEST_ADMIN_DSN` and `KEEL_M103_TEST_INSTALLER_DSN` securely
through the operator environment. Tests require loopback connections to the same
explicitly named test database. From `backend`:

```text
python -m pytest -q tests/migrations/test_notification_installer.py src/ai/tests/test_migration_filenames.py
```

Tests execute real SQL with both authorities: the original failure, successful
installation, attributes/memberships, function ownership and ACLs, two-tenant
RLS, unsafe states, insufficient installer authority, exact membership
restoration, rollback, and committed migration-history replay. No cloud migration
or full 168-migration sequence is covered by these focused tests.

Execution on 2026-11-06: **26 passed in 3.00 seconds**, using actual local
PostgreSQL 17 superuser and non-superuser connections. Historical SQL files are
byte-for-byte unchanged in Git. Read-only cloud checks confirmed the Neon
installer is non-superuser but has BYPASSRLS and membership in `neon_superuser`;
it is installation authority only. `ceopro_app` has neither SUPERUSER nor
BYPASSRLS and has no reachable role memberships. The new definer owner is still
absent on Neon, consistent with the rolled-back migration 103.

## Migration 103 continuation: historical checkpoint

Before integration of the migration-103 correction, Neon project
`damp-river-41978380` was at 102/168 with migration 103 absent.
The existing local disposable database has already applied migration 103 and is
not a target for this correction. After separate integration/publication and
cloud-execution approval, verify project/database identity and the 102-entry
ledger, back up the current partial database, and run the existing migration
runner with the protected installation URL and fresh restricted-role passwords.
It will skip the 102 committed filenames and attempt 103 atomically. Do not
manually grant privileges, mark migrations applied, or copy installer credentials
to the API. Stop on any subsequent failure.

Inspection found the same non-superuser function-ownership/ACL assumptions in
migrations 141 (`20261112000000_billing_setup_service.sql`), 143
(`20261113000000_billing_reconciliation_roles.sql`), 144
(`20261113000100_billing_context_guards.sql`), and 165
(`20261127000000_provider_backed_trials.sql`). They are unchanged and have not
been executed under Neon-compatible authority here. This correction does not
establish that the complete migration sequence is Neon-compatible.

## Migration 141: isolated correction, not yet integrated or run on Neon

Read-only verification on 2026-11-06 confirmed the dedicated Neon database is
now at 140/168. Migration 103 is committed. Migration 141 rolled back:
`ceopro_billing_setup`, `ceopro_trial_issuer` and
`public.billing_setup_trial(text,boolean)` are absent. The installer is a
non-superuser Neon installation owner; runtime roles have not gained privileged
memberships. No cloud mutation was performed during this correction task.

Migration `20261112000000_billing_setup_service.sql` creates restricted setup
and trial-issuer roles, installs tenant/billing-role policies and a SECURITY
DEFINER function with fixed `pg_catalog,public,pg_temp` search path. Ownership
belongs to the NOLOGIN issuer; execution belongs only to the LOGIN setup role.
The function validates an active principal and billing permissions, locks
person/tenant trial eligibility, and implements the historical trial rules.
Those rules and every historical SQL file are unchanged by this correction.

PostgreSQL 17 requires SET authority to the new owner, plus schema CREATE for
that owner, for `ALTER FUNCTION ... OWNER TO`. The original migration has
neither prerequisite for a fresh non-superuser installer. Inheritance is also
needed to perform the original ACL revocation/grant after transferring ownership.

`scripts/migration_141_compat.py` is dispatched only for this exact filename
and SHA-256-pinned source. It reuses migration 103's read-only membership
snapshot utility; migration 103's implementation is unchanged.

The true-superuser path runs the original SQL and verifies the result. The
non-superuser path runs the original prefix, validates both restricted roles,
and supplies temporary schema CREATE to the NOLOGIN issuer and, only if needed,
temporary SET/inheritance to the installer. It executes exactly these original
statements:

```sql
ALTER FUNCTION public.billing_setup_trial(TEXT,BOOLEAN) OWNER TO ceopro_trial_issuer;
REVOKE ALL ON FUNCTION public.billing_setup_trial(TEXT,BOOLEAN) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.billing_setup_trial(TEXT,BOOLEAN) TO ceopro_billing_setup;
```

Schema CREATE and temporary memberships are restored immediately afterward,
with exact ACL/membership comparisons. The unchanged migration tail then runs,
including its original checks against inherited schema/database CREATE. Every
operation is in the existing per-file transaction; autocommit and changed source
are rejected. A failure propagates to the runner's rollback; no error is swallowed.

Final verification checks all role attributes (LOGIN only for setup), outbound
memberships and unexpected grantees/ownership, the one exact function owner and
definer search path, the exact owner/setup execution ACL (no PUBLIC/app/extra
grantees or delegation), and FORCE RLS on all six relevant tenant/billing tables.
No SUPERUSER, BYPASSRLS, CREATEROLE or persistent DDL permission is granted.

### Focused verification and boundaries

Use a new, loopback-only PostgreSQL 17 test cluster. The unchanged migration-103
suite runs against its dedicated 102-migration database. A separate
`keel_m141_test` database contains the first 140 migrations, owned by the same
restricted installation authority. Provide the two appropriate guarded DSNs as
`KEEL_M141_TEST_ADMIN_DSN` and `KEEL_M141_TEST_INSTALLER_DSN`, then from `backend`:

```text
python -m pytest -q tests/migrations/test_billing_setup_installer.py
```

The suite uses real superuser and non-superuser connections, verifies both
original failures (SET and schema CREATE), function-body equality, role/ACL/RLS
checks, exact membership restoration for existing grants, and rollback while
temporary grants are active. A separate test clone commits migration 141,
verifies ledger replay, and connects as the actual restricted setup role using
a freshly generated test password. Valid tenant contexts can perform the
read-only eligibility query; mismatched/absent principals and direct subscription
writes are denied. No trial/assignment is created, and no provider is called.
The unchanged migration-103 suite passed 26 tests with the new runner dispatch.
Final migration-141 execution on 2026-11-06: **28 passed in 2.79 seconds**.
The two focused runs therefore passed 54 tests in total; they used independent
102- and 140-migration baselines in one newly created local PostgreSQL 17 test
cluster. No cloud migrations or complete 168-migration sequence were run.

### Later migration inspection only

The following original operations still have the ownership/ACL compatibility
assumption. No correction or execution of these later migrations is included:

| Migration | Exact ownership operation | Required execution boundary |
|---|---|---|
| 143 | `ALTER FUNCTION public.billing_provider_tenant(text,text) OWNER TO ceopro_billing_lookup` | Only `ceopro_billing_webhook`; exact provider-reference routing and session-role check |
| 143 | `ALTER FUNCTION public.billing_provider_month_spend(text,text,timestamptz) OWNER TO ceopro_billing_lookup` | Only `ceopro_credit_accounting`; aggregate provider accounting |
| 143 | `ALTER FUNCTION public.billing_expired_credit_tenants(integer) OWNER TO ceopro_billing_lookup` | Only `ceopro_credit_accounting`; bounded stale-reservation tenant enumeration |
| 143 | `ALTER FUNCTION public.billing_setup_schedule(text,text,text) OWNER TO ceopro_schedule_writer` | Only `ceopro_billing_setup`; active billing principal and tenant-scoped scheduling metadata |
| 144 | `ALTER FUNCTION public.billing_accounting_principal(uuid,uuid) OWNER TO ceopro_schedule_writer` | Only `ceopro_credit_accounting`; matching active actor/tenant and membership row locking |
| 165 | `ALTER FUNCTION public.billing_reserve_trial_checkout(UUID,TEXT,TEXT) OWNER TO ceopro_trial_issuer` | Only `ceopro_billing_setup`; validated checkout/trial reservation |
| 165 | `ALTER FUNCTION public.billing_release_trial_checkout(UUID) OWNER TO ceopro_trial_issuer` | Only `ceopro_billing_setup`; own authorized expired attempt |
| 165 | `ALTER FUNCTION public.billing_expire_trial_checkout(UUID,TEXT) OWNER TO ceopro_trial_issuer` | Only `ceopro_billing_webhook`; bound verified receipt and matching checkout session |
| 165 | `ALTER FUNCTION public.billing_confirm_trial_checkout(UUID,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ) OWNER TO ceopro_trial_issuer` | Only `ceopro_billing_webhook`; provider-bound receipt, immutable terms and one-time eligibility |

Migration 165 also contains `CREATE OR REPLACE FUNCTION
public.billing_setup_trial(p_plan TEXT,p_start BOOLEAN DEFAULT FALSE)`, replacing
the issuer-owned function to reject local/cardless activation. That replacement
requires owner authority before the later OWNER TO statements. Any future
compatibility correction must preserve that provider-confirmation boundary,
NOLOGIN/non-BYPASSRLS ownership, fixed definer search paths, restricted ACLs and
tenant policies. Do not deploy a partially initialized 141-migration schema.

### Safest continuation after separate approval

Review and fast-forward the isolated fix from accepted `5cf4fc13`, publish only
the approved demo revision, then verify Free project `damp-river-41978380`,
database identity and exact first-140 ledger. Create/read-verify a fresh protected
backup. Resume the existing runner with installation-only credentials; it skips
the 140 committed filenames and attempts 141 atomically. Verify the restricted
roles, exact function ACL and removal of temporary CREATE/SET/inheritance.
Stop on any next failure. Do not manually grant permissions or mark migrations
applied. Later risks above remain separate work; all 168 have not been verified.

References: [PostgreSQL 17 ALTER ROLE](https://www.postgresql.org/docs/17/sql-alterrole.html),
[PostgreSQL role privileges](https://www.postgresql.org/docs/17/ddl-priv.html),
[Neon roles](https://neon.com/docs/manage/roles).

## Consolidated follow-up: migrations 142, 143, 144 and 165

Starting revision: `59736091595e753eaa869045745c0424c1163a95`.
Isolated branch: `fix/neon-remaining-migration-compatibility`.
Neon project `damp-river-41978380` remains at **141/168**. No cloud migration,
integration, publication or Render provisioning is part of this correction.

### Root causes and exact scope

| Migration | Cause | Restricted owner / permitted caller |
|---|---|---|
| 142 `20261112000100_billing_setup_command_guards.sql` | `CREATE OR REPLACE billing_setup_trial` replaces the issuer-owned function from 141; the installer lacks inherited owner authority | `ceopro_trial_issuer` / `ceopro_billing_setup` |
| 143 `20261113000000_billing_reconciliation_roles.sql` | Four `OWNER TO` operations need installer SET authority and schema CREATE for the new owner; subsequent ACL statements need inherited owner authority | Three lookup functions: `ceopro_billing_lookup` / webhook or accounting; schedule function: `ceopro_schedule_writer` / setup |
| 144 `20261113000100_billing_context_guards.sql` | The same transfer/ACL requirements for `billing_accounting_principal` | `ceopro_schedule_writer` / `ceopro_credit_accounting` |
| 165 `20261127000000_provider_backed_trials.sql` | Replaces the issuer-owned eligibility function, then transfers four checkout functions and restricts execution | `ceopro_trial_issuer` / setup for reserve/release, webhook for expire/confirm |

The original migration-142 ownership error and the other three migrations'
unassisted permission failures are reproduced on real PostgreSQL 17. Migration
165's replacement must continue rejecting local trial activation; only its
original provider-confirmation functions may activate a trial.

`scripts/migration_remaining_compat.py` pins the four exact filenames and
newline-normalized UTF-8 SHA-256 values:

| Migration | SHA-256 |
|---|---|
| 142 | `d051bc881dd30b538e5238879846958cebffd1aac21f996659c7a2161c68c07e` |
| 143 | `3259aefc1155c0b227f1b8abfa54bbafa51879081ec2edfeaac5d2c35c9c53a7` |
| 144 | `e005e44a285047413c7d5ce3ecc674b5ee7f6a4b5aa727a8e45394fcc47b6bbe` |
| 165 | `2094b613bd025cbd2230f98e12faa75ae515fa80cb35406e78ab0d2b3a0b9ded` |

Only fixed reviewed function-replacement statements and three-statement
OWNER/REVOKE/GRANT spans receive compatibility handling. Other statements run
unchanged as the installer. The dispatcher adds only these four filenames;
the existing migration-103 and migration-141 implementations are unchanged.

Replacement uses temporary installer inheritance of the existing restricted
owner; it does not require SET ROLE or schema CREATE. Transfers temporarily
provide installer inheritance/SET and new-owner schema CREATE. These grants
are uncommitted, restricted to each reviewed span, and removed before any
migration commit. The installer must already have PostgreSQL ADMIN authority;
the helper cannot manufacture it. No role receives SUPERUSER or BYPASSRLS.
There is no arbitrary SQL callback, role impersonation or general migration
privilege override.

### Security and rollback guarantees

- A changed source hash, unknown filename or autocommit connection is rejected.
- Owners must be NOLOGIN and have all six elevation/inheritance flags false.
  Callers retain only their expected LOGIN flag. Outbound memberships,
  unexpected incoming grantees, table/schema/database ownership and effective
  schema/database CREATE are rejected. Incoming installation grants are limited
  to the active installer/database owner, accommodating superuser verification
  of a baseline created by the restricted installer.
- Each target function must have the reviewed owner, SECURITY DEFINER, no
  LEAKPROOF flag and exactly `search_path=pg_catalog, public, pg_temp`.
  Replacement also verifies the exact previous function-body hash before any
  grant. New transfers must start installer-owned.
- Final execution ACLs must contain exactly owner and intended caller EXECUTE,
  issued by the owner, without delegation or PUBLIC/application access. A
  transfer preserves the original body; replacement verifies the new body hash.
- Every privilege window has a savepoint. SQL errors and verification failures
  roll back that window and propagate. The runner then rolls back the whole
  migration, including policies, new roles/functions and its ledger entry.
  Exact memberships (grantor, member, ADMIN, INHERIT, SET), schema ACL and
  current/session user, role setting and search path are compared after success.
- Existing FORCE RLS is checked on the relevant tenant, subscription, checkout,
  receipt, ledger and balance tables. The functions' original policies, receipt
  association, active-principal checks and payment gates remain unchanged.

### Focused local verification

Use a new task-only, loopback-bound PostgreSQL 17 cluster, not an application
database. Initialize dedicated `keel_m103_test` and `keel_m141_test` baselines
for the existing suites. Then clone the 140 baseline to `keel_remaining_test`
and apply 141. The installer owns the databases and has the installation-only
CREATEROLE/CREATEDB/REPLICATION/BYPASSRLS attributes observed for the Neon
installer, **not SUPERUSER**. Runtime logins have none of those attributes.
The local superuser preinstalls vector to model managed-extension installation.

Provide guarded DSNs through a protected operator process:

```text
KEEL_M103_TEST_ADMIN_DSN / KEEL_M103_TEST_INSTALLER_DSN
KEEL_M141_TEST_ADMIN_DSN / KEEL_M141_TEST_INSTALLER_DSN
KEEL_MREMAINING_TEST_ADMIN_DSN / KEEL_MREMAINING_TEST_INSTALLER_DSN
```

Run each suite in order from `backend` (the cluster-wide role fixtures are
deliberately separate; do not run these suites concurrently):

```text
python -m pytest -q --tb=short tests/migrations/test_notification_installer.py src/ai/tests/test_migration_filenames.py
python -m pytest -q --tb=short tests/migrations/test_billing_setup_installer.py
python -m pytest -q --tb=short tests/migrations/test_remaining_installer.py
```

The remaining suite uses real superuser and restricted installer connections.
It covers all four unassisted failures, all four corrected migrations, exact
SQL-body preservation, source/transaction guards, role/owner/ACL/body/search-path
and RLS rejection, existing ADMIN/INHERIT/SET grant restoration, missing installer
ADMIN authority, and injected failures while temporary authority is active.
Runner failure leaves the ledger at 141 and restores the old function body.

Two separate committed clones execute **all 27 migrations from 142 through 168**,
one under each installation authority, reaching **168/168**. Re-running the
runner applies zero migrations. The original first-141 ledger is retained.
Original intermediate migrations run through the standard unchanged path.

Fresh actual `ceopro_app`, setup, webhook and accounting connections verify:
tenant-scoped product/invoice reads and denied cross-tenant updates; denied
application access to trusted functions; setup eligibility without activation;
rejection of cardless activation, mismatched principals and direct subscription
writes; webhook receipt-bound confirmation denial without a verified receipt;
valid accounting principal row-lock checks, mismatched-context rejection and
denied membership writes. Product/invoice amounts and JOD currency survive the
sequence. No trials, subscriptions, plan assignments or usage-ledger rows are
created by these checks. Restricted image-worker attributes, vector/pg_trgm,
function ownership/ACLs, memberships and FORCE RLS are checked after 168.

This is local PostgreSQL compatibility evidence, **not a successful Neon
142–168 execution claim**. No provider requests or existing fixture writes occur.

Final results on 2026-11-06: existing 103/filename checks **26 passed**, existing
141 checks **28 passed**, consolidated checks **55 passed in 14.81 seconds**:
**109 focused tests passed**, with no skipped database cases. Intermediate
test-development failures were corrected invalid test setup/expectations
(including the unchanged ceopro_app INHERIT flag); the final run above is the
acceptance result. No security attributes or historical SQL were changed to
satisfy a test. The temporary container uses cached `pgvector/pgvector:0.8.6-pg17`,
loopback-only networking and no existing volumes. Redacted operator logs are
retained locally in the protected `.keel-competition/20261109` directory as
`remaining-test103.log`, `remaining-test141.log`, and `remaining-newtests.log`.

### Remaining sequence assessment

Inspection of all migrations 142–168 found no additional owner-transfer boundary
requiring this helper. Other function replacements, renames, grants and policies
operate on installer-owned objects, including provider accounting (152), billing
catalog wrappers (159/167), image-worker functions (164), and discount validation
(168). Migration 145's grant to the schedule writer remains unchanged and passes.
The complete local sequence provides execution evidence for these observations.
Managed-service-specific differences remain possible until Neon is resumed;
stop on any failure rather than adding privileges or marking files applied.

### Safest Neon continuation — separate approval required

1. Review this isolated commit and clean worktree; verify ancestry from `5973609`.
   Fast-forward integration and only the demo branch, then publish that exact
   approved demo revision. Do not change main or Marketing PRs.
2. Reconfirm Free project `damp-river-41978380`, its dedicated database and installer,
   the exact first-141 ledger, absence of 142, and restricted role conditions.
   Leave the other Neon project named KEEL untouched.
3. Create a fresh protected custom-format backup; inspect its TOC and database
   identity. Keep migration-owner credentials only in the operator process.
4. From the reviewed backend checkout, use the existing command with the NEW
   demo database's installation DSN and protected restricted-role passwords:
   `python scripts/apply_migrations.py`. No manual grants or SQL rewrites. It
   skips 141 entries and handles only the four pinned migration files specially.
5. Stop immediately at any unexpected error. Each preceding successful migration
   remains committed; the failed file and temporary privileges roll back.
6. After success, verify 168 exact ledger filenames, extensions, restricted role
   attributes/memberships, function owners/ACLs/search paths, FORCE RLS and no
   retained temporary CREATE/INHERIT/SET. Verify restricted application connections
   before declaring the database initialized or proceeding to Render Free.

References: [PostgreSQL 17 CREATE FUNCTION](https://www.postgresql.org/docs/17/sql-createfunction.html),
[ALTER FUNCTION](https://www.postgresql.org/docs/17/sql-alterfunction.html),
[GRANT](https://www.postgresql.org/docs/17/sql-grant.html).
