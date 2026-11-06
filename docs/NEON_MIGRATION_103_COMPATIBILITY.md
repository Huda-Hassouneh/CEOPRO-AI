# Migration 103: managed PostgreSQL installer compatibility

This is an installer-only correction. It does not change runtime authorization,
RLS policies, billing, or any historical SQL migration.

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

## Approved continuation only

Neon project `damp-river-41978380` remains at 102/168 with migration 103 absent.
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

References: [PostgreSQL 17 ALTER ROLE](https://www.postgresql.org/docs/17/sql-alterrole.html),
[PostgreSQL role privileges](https://www.postgresql.org/docs/17/ddl-priv.html),
[Neon roles](https://neon.com/docs/manage/roles).
