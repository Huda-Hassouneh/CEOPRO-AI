"""
KEEL - records the size of each file a company stores outside the
assistant's documents (marketing images, kept upload results), so the
plan's storage limit counts them (tenant_storage_objects, migration
20261013000100). The caller's connection carries the company's row-level
security context; the caller commits.
"""


def record(conn, tenant_id: str, bucket: str, object_key: str, size_bytes: int, kind: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO tenant_storage_objects (tenant_id, bucket, object_key, size_bytes, kind)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (bucket, object_key) DO UPDATE SET size_bytes = EXCLUDED.size_bytes;
            """,
            (tenant_id, bucket, object_key, max(0, int(size_bytes)), kind),
        )


def forget(conn, tenant_id: str, bucket: str, object_key: str) -> None:
    """The file was deleted: it no longer counts toward storage."""
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM tenant_storage_objects WHERE tenant_id = %s AND bucket = %s AND object_key = %s;",
                       (tenant_id, bucket, object_key))
