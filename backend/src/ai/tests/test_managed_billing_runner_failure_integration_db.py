"""Installer failure must release authority, on dedicated native fixtures only."""
import psycopg2
import pytest

from .test_managed_postgres_migrations_integration_db import (
    ADMIN_URL, APP_PASSWORD, OWNER, _snapshot, built,
)

pytestmark = pytest.mark.skipif(not ADMIN_URL or not APP_PASSWORD,
    reason='Dedicated disposable managed installer cluster required')


def test_failure_and_replay_release_all_temporary_billing_memberships(built, tmp_path, monkeypatch):
    from scripts import apply_migrations as migrations

    before = _snapshot(built['neon_url'])
    folder = tmp_path / 'failing-migrations'
    folder.mkdir()
    (folder / '99999999999999_failure_probe.sql').write_text('SELECT 1/0;', encoding='utf-8')
    with psycopg2.connect(built['neon_url']) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(migrations, 'MIGRATIONS_DIR', folder)
            with pytest.raises(psycopg2.errors.DivisionByZero):
                migrations.run(conn)
        with conn.cursor() as cur:
            cur.execute("""SELECT r.rolname FROM pg_auth_members a
                JOIN pg_roles r ON r.oid=a.roleid JOIN pg_roles m ON m.oid=a.member
                WHERE m.rolname=%s AND r.rolname ~ '^(ceopro|keel)_'
                  AND (a.set_option OR a.inherit_option)""", (OWNER,))
            assert cur.fetchall() == []
            cur.execute("SELECT count(*) FROM schema_migrations WHERE filename='99999999999999_failure_probe.sql'")
            assert cur.fetchone()[0] == 0
        assert migrations.run(conn) == []
    assert _snapshot(built['neon_url']) == before
