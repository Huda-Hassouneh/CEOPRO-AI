"""
KEEL - records the size of each file a company stores outside the
assistant's documents (marketing images, kept upload results), so the
plan's storage limit counts them (tenant_storage_objects, migration
20261013000100). The caller's connection carries the company's row-level
security context; the caller commits.
"""
import logging

logger = logging.getLogger(__name__)


def record(conn, tenant_id: str, bucket: str, object_key: str, size_bytes: int, kind: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenant_storage_objects (tenant_id, bucket, object_key, size_bytes, kind)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (bucket, object_key) DO UPDATE
            SET size_bytes = EXCLUDED.size_bytes, created_at = NOW();
            """,
            (tenant_id, bucket, object_key, max(0, int(size_bytes)), kind),
        )


def stale_records(conn, tenant_id: str, kind_prefix: str, older_than, limit: int = 100) -> list:
    """Return old tenant-owned ledger entries for conservative lazy recovery.

    The caller must verify the object and its application reference before
    removing either the object or its ledger entry. ``created_at`` is refreshed
    by ``record`` so a retry starts a new recovery grace period.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT bucket, object_key, size_bytes, kind, created_at
            FROM tenant_storage_objects
            WHERE tenant_id = %s AND LEFT(kind, %s) = %s AND created_at < %s
            ORDER BY created_at ASC
            LIMIT %s;
            """,
            (tenant_id, len(kind_prefix), kind_prefix, older_than, max(1, min(int(limit), 500))),
        )
        return cursor.fetchall()


def recover_stale(
    conn, tenant_id: str, kind_prefix: str, older_than, object_exists,
    is_referenced=None, remove_object=None, limit: int = 100,
) -> int:
    """Conservatively reconcile old ledger entries using caller-owned evidence.

    ``object_exists`` returns True/False, or raises when storage state is
    inconclusive. Missing objects may be forgotten. Existing objects are
    retained unless a caller proves they are unreferenced and supplies a
    deletion callback that returns exactly True only after confirmed cleanup.
    RLS and the explicit tenant filter scope the scan.
    """
    rows = stale_records(conn, tenant_id, kind_prefix, older_than, limit)
    recovered = 0
    for bucket, object_key, _size_bytes, _kind, _created_at in rows:
        try:
            if is_referenced is not None and is_referenced(bucket, object_key):
                continue
            exists = object_exists(bucket, object_key)
            if exists is None:
                continue
            if exists:
                if remove_object is None or remove_object(bucket, object_key) is not True:
                    continue
            forget(conn, tenant_id, bucket, object_key)
            conn.commit()
            recovered += 1
        except Exception:
            conn.rollback()
            logger.exception("Could not recover stale storage record (tenant=%s key=%s)", tenant_id, object_key)
    return recovered


def forget(conn, tenant_id: str, bucket: str, object_key: str) -> None:
    """The file was deleted: it no longer counts toward storage."""
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM tenant_storage_objects WHERE tenant_id = %s AND bucket = %s AND object_key = %s;",
                       (tenant_id, bucket, object_key))


def remove_object_and_forget(
    conn, tenant_id: str, bucket: str, object_key: str, remove_object,
) -> None:
    """Remove a remote object before releasing its storage accounting.

    The callback must treat an already-missing object as successful removal.
    If remote deletion fails, ``forget`` is never called, so the tenant keeps
    its existing counted bytes. If the database transaction later fails, the
    retained row is conservative and a retry can repeat the idempotent delete.
    """
    remove_object()
    forget(conn, tenant_id, bucket, object_key)


def compensate_upload(
    conn, tenant_id: str, bucket: str, object_key: str, size_bytes: int, kind: str,
    remove_object,
) -> bool:
    """Compensate an upload after its later database operation failed.

    A confirmed remote removal is followed by an idempotent ledger delete.
    If removal cannot be confirmed, retain/create the ledger entry so the
    stored bytes remain included in quota usage. The caller commits this
    transaction and re-raises the original database error.

    Returns True only when object removal was confirmed.
    """
    try:
        remove_object()
    except Exception:
        record(conn, tenant_id, bucket, object_key, size_bytes, kind)
        return False

    forget(conn, tenant_id, bucket, object_key)
    return True
