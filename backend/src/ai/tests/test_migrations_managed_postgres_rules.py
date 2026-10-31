"""Static rules that keep every migration runnable by a non-superuser owner (Neon).

The full proof is test_managed_postgres_migrations_integration_db.py, which
needs a dedicated cluster; these checks run everywhere without a database.
"""
import re
from pathlib import Path

MIGRATIONS = sorted((Path(__file__).resolve().parents[2] / "infrastructure" / "database" / "migrations").glob("*.sql"))

ALTER_ROLE = re.compile(r"^\s*ALTER\s+ROLE\s+(\w+)(?P<rest>[^;]*);", re.I | re.M)
SUPERUSER_ONLY = re.compile(r"\b(NO)?(SUPERUSER|BYPASSRLS|REPLICATION)\b", re.I)
OWNER_TO = re.compile(r"^ALTER FUNCTION (public\.\w+)\([^)]*\) OWNER TO (\w+);", re.I)
FUNCTION_ACL = re.compile(r"^(?:REVOKE ALL|GRANT EXECUTE) ON FUNCTION (public\.\w+)\(", re.I)
TAKE = re.compile(r"^GRANT (\w+) TO CURRENT_USER;", re.I)
DROP = re.compile(r"^REVOKE (\w+) FROM CURRENT_USER;", re.I)


def test_no_migration_changes_superuser_only_role_attributes():
    offenders = [f"{path.name}: ALTER ROLE {m.group(1)}{m.group('rest')}"
                 for path in MIGRATIONS for m in ALTER_ROLE.finditer(path.read_text())
                 if SUPERUSER_ONLY.search(m.group("rest"))]
    assert offenders == [], "Neon refuses these without SUPERUSER:\n" + "\n".join(offenders)


def test_ownership_transfers_and_owner_grants_hold_the_owner_role():
    problems = []
    for path in MIGRATIONS:
        held, owners = set(), {}
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if match := TAKE.match(line):
                held.add(match.group(1))
            elif match := DROP.match(line):
                held.discard(match.group(1))
            elif match := OWNER_TO.match(line):
                function, role = match.groups()
                owners[function] = role
                if role not in held:
                    problems.append(f"{path.name}:{number} OWNER TO {role} without GRANT {role} TO CURRENT_USER")
            elif (match := FUNCTION_ACL.match(line)) and match.group(1) in owners:
                role = owners[match.group(1)]
                if role not in held:  # A non-owner's GRANT/REVOKE is skipped with only a warning.
                    problems.append(f"{path.name}:{number} grant on {match.group(1)} after leaving {role}")
        if held:
            problems.append(f"{path.name}: still holds {sorted(held)} at the end")
    assert problems == [], "\n".join(problems)
