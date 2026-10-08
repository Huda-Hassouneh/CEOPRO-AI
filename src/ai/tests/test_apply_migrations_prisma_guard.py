"""scripts/apply_migrations.py must not replay migrations/ onto a database
the web backend's Prisma migrations built (the hosted Render one): most of
those files are already applied there under other names."""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "apply_migrations", Path(__file__).resolve().parents[3] / "scripts" / "apply_migrations.py")
apply_migrations = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apply_migrations)


class _Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.statements.append(sql)
        self._result = (params[0] in self.conn.tables,) if params else None

    def fetchone(self):
        return self._result


class _Conn:
    def __init__(self, tables):
        self.tables = set(tables)
        self.statements = []

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass


def test_prisma_managed_database_is_refused_before_any_change():
    conn = _Conn({"_prisma_migrations", "companies"})
    with pytest.raises(RuntimeError, match="Prisma"):
        apply_migrations.run(conn)
    assert all(s.lstrip().upper().startswith("SELECT") for s in conn.statements)


def test_database_with_both_histories_is_left_to_schema_migrations(monkeypatch):
    # Once this runner has tracked a database, the Prisma table alone is no reason to stop.
    conn = _Conn({"_prisma_migrations", "schema_migrations", "companies"})
    monkeypatch.setattr(apply_migrations, "_already_applied",
                        lambda c: {p.name for p in apply_migrations.MIGRATIONS_DIR.glob("*.sql")})
    assert apply_migrations.run(conn) == []
