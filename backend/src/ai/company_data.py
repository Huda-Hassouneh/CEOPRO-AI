"""
A company's own data, all of it: a downloadable export and permanent
deletion - what the privacy policy promises.

Export reads every table that carries the company's tenant_id through the
company's own row-level-security context, leaving out secrets (stored
credentials, sign-in tokens, password hashes) and machine-only columns
(embeddings). Deletion removes the company and everything that belongs to
it, including stored files, after refusing while a paid subscription is
still running.
"""
import io
import json
import logging
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

logger = logging.getLogger("APEX_COMPANY_DATA")

# Never exported: sign-in secrets, stored connector credentials, billing
# provider event payloads and internal counters.
SKIP_TABLES = {"auth_tokens", "billing_webhook_events", "tenant_usage_counters", "import_staging_rows",
               "market_observation_staging"}
SKIP_COLUMNS = {"connection_credentials_vault", "embedding", "password_hash", "token_hash"}
# Children that block their parent's deletion (ON DELETE RESTRICT); removed first.
RESTRICTED_CHILDREN = ("invoice_items", "competitor_product_mappings", "market_alert_events", "market_events")


class DeletionBlocked(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        return None
    return str(value)


def tenant_tables(conn) -> list:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.table_name, array_agg(c.column_name::text ORDER BY c.ordinal_position)
            FROM information_schema.columns c
            JOIN information_schema.tables t ON t.table_name = c.table_name AND t.table_schema = c.table_schema
            WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
              AND c.table_name IN (SELECT table_name FROM information_schema.columns
                                   WHERE table_schema = 'public' AND column_name = 'tenant_id')
            GROUP BY c.table_name ORDER BY c.table_name;
            """
        )
        return [(name, [col for col in cols if col not in SKIP_COLUMNS])
                for name, cols in cursor.fetchall() if name not in SKIP_TABLES]


def export_company(conn, tenant_id: str) -> bytes:
    """A zip with one JSON-lines file per table, the team list and a manifest."""
    buffer = io.BytesIO()
    manifest = {"exported_at": datetime.now(timezone.utc).isoformat(), "tenant_id": tenant_id, "tables": {}}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for table, columns in tenant_tables(conn):
            quoted = ", ".join(f'"{c}"' for c in columns)
            with conn.cursor() as cursor:
                cursor.execute("SAVEPOINT export_table;")
                try:
                    cursor.execute(f'SELECT {quoted} FROM "{table}" WHERE tenant_id = %s;', (tenant_id,))
                    rows = cursor.fetchall()
                    cursor.execute("RELEASE SAVEPOINT export_table;")
                except Exception:  # noqa: BLE001 - a table this role can't read is listed, not fatal
                    cursor.execute("ROLLBACK TO SAVEPOINT export_table;")
                    manifest["tables"][table] = {"rows": None, "note": "not readable"}
                    continue
            if not rows:
                continue
            lines = "\n".join(json.dumps(dict(zip(columns, row)), default=_json_default, ensure_ascii=False) for row in rows)
            archive.writestr(f"data/{table}.jsonl", lines + "\n")
            manifest["tables"][table] = {"rows": len(rows)}
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT u.email, u.full_name, tu.role_key, tu.joined_at, tu.removed_at
                FROM tenant_users tu JOIN users u ON u.user_id = tu.user_id WHERE tu.tenant_id = %s;
                """,
                (tenant_id,),
            )
            team = [dict(zip(("email", "full_name", "role", "joined_at", "removed_at"), row)) for row in cursor.fetchall()]
        archive.writestr("team.json", json.dumps(team, default=_json_default, ensure_ascii=False, indent=2))
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("README.txt", (
            "KEEL company data export\n\n"
            "data/<table>.jsonl - one JSON object per line for every record your company owns.\n"
            "team.json - the people with access to this company.\n"
            "manifest.json - when this was exported and how many records each file holds.\n\n"
            "Not included: passwords, sign-in tokens, stored connector credentials and search embeddings.\n"
        ))
    return buffer.getvalue()


def _paid_subscription_running(cursor, tenant_id: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM billing_subscriptions
        WHERE tenant_id = %s AND stripe_subscription_id IS NOT NULL
          AND status IN ('active', 'trialing', 'past_due', 'payment_failed', 'paused')
          AND NOT cancel_at_period_end;
        """,
        (tenant_id,),
    )
    return cursor.fetchone() is not None


def delete_company(sys_conn, tenant_id: str) -> dict:
    """Deletes the company and everything it owns. `sys_conn` is a system
    (owner-privileged) connection; the caller has already checked that the
    requester is the company's owner. Returns the stored-file keys to remove."""
    with sys_conn.cursor() as cursor:
        cursor.execute("SELECT business_name FROM companies WHERE tenant_id = %s FOR UPDATE;", (tenant_id,))
        if cursor.fetchone() is None:
            raise DeletionBlocked("not_found")
        if _paid_subscription_running(cursor, tenant_id):
            raise DeletionBlocked("subscription_active")
        # Existing immutable import/provider evidence uses intentional RESTRICT
        # constraints. Surface the pending retention review, never bypass it or
        # let a customer-facing deletion fail halfway through with an SQL error.
        for table in ('keel_import_batches','keel_provider_sources'):
            cursor.execute("SELECT to_regclass(%s)",('public.'+table,))
            if cursor.fetchone()[0] is not None:
                cursor.execute(f'SELECT 1 FROM "{table}" WHERE tenant_id=%s LIMIT 1',(tenant_id,))
                if cursor.fetchone() is not None:
                    raise DeletionBlocked('integration_evidence_review')
        cursor.execute("SELECT storage_bucket_path FROM rag_documents_metadata WHERE tenant_id = %s AND storage_bucket_path IS NOT NULL;", (tenant_id,))
        rag_objects = [row[0] for row in cursor.fetchall()]
        counts = {}
        for table in RESTRICTED_CHILDREN:
            cursor.execute(f'DELETE FROM "{table}" WHERE tenant_id = %s;', (tenant_id,))
            counts[table] = cursor.rowcount
        cursor.execute("DELETE FROM global_competitors WHERE added_by_tenant_id = %s AND visibility = 'PRIVATE';", (tenant_id,))
        cursor.execute("DELETE FROM companies WHERE tenant_id = %s;", (tenant_id,))
    return {"rag_objects": rag_objects, "counts": counts}


def remove_stored_files(minio_client, tenant_id: str, rag_objects: list) -> int:
    """Best effort: files are removed after the records are gone; a storage
    error is logged for an operator, never shown as a failed deletion."""
    from src.ai.extraction.minio_persistence import EXTRACTION_RESULTS_BUCKET
    from src.ai.marketing.image_storage import GENERATED_IMAGES_BUCKET, PROCESSED_IMAGES_BUCKET, SOURCE_IMAGES_BUCKET
    from src.ai.rag.pipeline import DEFAULT_BUCKET as RAG_BUCKET

    removed = 0
    for bucket in (EXTRACTION_RESULTS_BUCKET, SOURCE_IMAGES_BUCKET, GENERATED_IMAGES_BUCKET, PROCESSED_IMAGES_BUCKET):
        try:
            if not minio_client.bucket_exists(bucket):
                continue
            for obj in minio_client.list_objects(bucket, prefix=f"{tenant_id}/", recursive=True):
                minio_client.remove_object(bucket, obj.object_name)
                removed += 1
        except Exception:  # noqa: BLE001
            logger.exception("could not remove stored files in %s for deleted company %s", bucket, tenant_id)
    for key in rag_objects:
        try:
            minio_client.remove_object(RAG_BUCKET, key)
            removed += 1
        except Exception:  # noqa: BLE001
            logger.exception("could not remove document %s for deleted company %s", key, tenant_id)
    return removed
