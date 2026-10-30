"""The actual runner rolls back a failed migration file on a test database."""

import uuid

import psycopg2
import pytest

from scripts import apply_migrations
from src.ai import db


def test_failed_migration_leaves_no_partial_table_or_success_ledger(
    owner_db, billing_connections, monkeypatch, tmp_path
):
    table = "review_rollback_" + uuid.uuid4().hex
    filename = "99999999999999_review_atomic_failure.sql"
    # Generated identifiers are fixed alphanumerics from this test, not input.
    (tmp_path / filename).write_text(
        f"CREATE TABLE {table}(value INTEGER); SELECT review_intentionally_missing_function();"
    )
    monkeypatch.setattr(apply_migrations, "MIGRATIONS_DIR", tmp_path)
    conn = db.system_connection()
    try:
        with pytest.raises(psycopg2.errors.UndefinedFunction):
            apply_migrations.run(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", ("public." + table,))
            assert cur.fetchone()[0] is None
            cur.execute(
                "SELECT count(*) FROM schema_migrations WHERE filename=%s", (filename,)
            )
            assert cur.fetchone()[0] == 0
    finally:
        conn.close()
