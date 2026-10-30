"""Focused, dependency-free tests for storage-ledger compensation ordering."""
import unittest

from src.ai.core import storage_ledger


class _Cursor:
    def __init__(self, statements, rows=None):
        self.statements = statements
        self.rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, statement, params=None):
        self.statements.append((" ".join(statement.split()), params))

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self):
        self.statements = []
        self.rows = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self.statements, self.rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class StorageLedgerCompensationTests(unittest.TestCase):
    def test_stale_scan_is_tenant_and_kind_scoped_and_bounded(self):
        conn = _Connection()
        cutoff = object()

        rows = storage_ledger.stale_records(conn, "tenant-a", "marketing_", cutoff, limit=900)

        self.assertEqual(rows, [])
        statement, params = conn.statements[-1]
        self.assertIn("WHERE tenant_id = %s AND LEFT(kind, %s) = %s AND created_at < %s", statement)
        self.assertEqual(params, ("tenant-a", len("marketing_"), "marketing_", cutoff, 500))

    def test_stale_recovery_requires_reference_and_confirmed_delete_evidence(self):
        conn = _Connection()
        conn.rows = [
            ("bucket", "absent", 1, "marketing_image", None),
            ("bucket", "active", 2, "marketing_image", None),
            ("bucket", "delete-failed", 3, "marketing_image", None),
            ("bucket", "deleted", 4, "marketing_image", None),
        ]
        existence = {"absent": False, "active": True, "delete-failed": True, "deleted": True}
        removed = []

        recovered = storage_ledger.recover_stale(
            conn,
            "tenant-a",
            "marketing_",
            object(),
            lambda _bucket, key: existence[key],
            is_referenced=lambda _bucket, key: key == "active",
            remove_object=lambda _bucket, key: removed.append(key) or key == "deleted",
        )

        deleted_keys = [params[2] for sql, params in conn.statements if sql.startswith("DELETE FROM")]
        self.assertEqual(recovered, 2)
        self.assertEqual(removed, ["delete-failed", "deleted"])
        self.assertEqual(deleted_keys, ["absent", "deleted"])
        self.assertEqual(conn.commits, 2)
        self.assertEqual(conn.rollbacks, 0)

    def test_stale_recovery_retains_accounting_when_storage_state_is_inconclusive(self):
        conn = _Connection()
        conn.rows = [("bucket", "uncertain", 9, "upload_result", None)]

        def bucket_unavailable(_bucket, _key):
            raise OSError("bucket unavailable")

        recovered = storage_ledger.recover_stale(
            conn, "tenant-a", "upload_result", object(), bucket_unavailable,
        )

        self.assertEqual(recovered, 0)
        self.assertFalse(any(sql.startswith("DELETE FROM") for sql, _ in conn.statements))
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_confirmed_object_removal_releases_only_the_tenant_entry(self):
        conn = _Connection()
        removals = []

        removed = storage_ledger.compensate_upload(
            conn, "tenant-a", "bucket", "tenant-a/key", 17, "image",
            lambda: removals.append("removed"),
        )

        self.assertTrue(removed)
        self.assertEqual(removals, ["removed"])
        statement, params = conn.statements[-1]
        self.assertTrue(statement.startswith("DELETE FROM tenant_storage_objects"))
        self.assertEqual(params, ("tenant-a", "bucket", "tenant-a/key"))

    def test_failed_object_removal_retains_counted_bytes(self):
        conn = _Connection()

        def fail_remove():
            raise OSError("object storage unavailable")

        removed = storage_ledger.compensate_upload(
            conn, "tenant-a", "bucket", "tenant-a/key", 17, "image", fail_remove,
        )

        self.assertFalse(removed)
        statement, params = conn.statements[-1]
        self.assertTrue(statement.startswith("INSERT INTO tenant_storage_objects"))
        self.assertEqual(params, ("tenant-a", "bucket", "tenant-a/key", 17, "image"))

    def test_delete_failure_never_releases_existing_storage_entry(self):
        conn = _Connection()

        with self.assertRaises(OSError):
            storage_ledger.remove_object_and_forget(
                conn, "tenant-a", "bucket", "tenant-a/key",
                lambda: (_ for _ in ()).throw(OSError("unavailable")),
            )

        self.assertEqual(conn.statements, [])

    def test_confirmed_duplicate_cleanup_is_idempotent(self):
        conn = _Connection()
        for _ in range(2):
            storage_ledger.remove_object_and_forget(
                conn, "tenant-a", "bucket", "tenant-a/key", lambda: None,
            )

        self.assertEqual(len(conn.statements), 2)
        self.assertTrue(all(s.startswith("DELETE FROM tenant_storage_objects") for s, _ in conn.statements))


if __name__ == "__main__":
    unittest.main()
