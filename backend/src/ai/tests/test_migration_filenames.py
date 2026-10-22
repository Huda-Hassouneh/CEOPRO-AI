"""Migration filenames are the keys in schema_migrations and the runner applies
them in sorted filename order, so a malformed name (wrong width, stray case)
would sort or track differently from its neighbours."""
import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "infrastructure" / "database" / "migrations"
NAME = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")


def test_migration_filenames_are_well_formed():
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert files, f"no migrations found in {MIGRATIONS_DIR}"
    bad = [f.name for f in files if not NAME.match(f.name)]
    assert not bad, f"migration names must be <14-digit timestamp>_<snake_case>.sql: {bad}"
