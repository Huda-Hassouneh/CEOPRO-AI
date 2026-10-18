"""
Operator tool for CREDENTIAL_VAULT_MASTER_KEY, the key that protects every
connector credential companies save (src/market_scraper/credential_vault.py).
Never prints a stored credential; `generate` is the only command that
prints a key, and only the new one, to your own terminal.

Usage (from backend/, with DATABASE_URL set to the schema-owning role for
`check` and `rewrap`):
    python -m scripts.vault_key generate          # a new Fernet key
    python -m scripts.vault_key validate          # is the configured key usable?
    python -m scripts.vault_key check             # can every stored credential be opened?
    python -m scripts.vault_key rewrap            # move every credential to the current key

Rotating the key without losing anything:
    1. `generate` a new key.
    2. Set CREDENTIAL_VAULT_MASTER_KEY=<new> and
       CREDENTIAL_VAULT_PREVIOUS_KEYS=<old> on the API and the workers.
    3. `check` (every credential opens), then `rewrap`, then `check` again
       (all on the current key).
    4. Remove CREDENTIAL_VAULT_PREVIOUS_KEYS.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.market_scraper import credential_vault  # noqa: E402


def _rows(cursor, lock: bool = False):
    cursor.execute(
        "SELECT tenant_id, source_id, connection_credentials_vault FROM data_sources "
        "WHERE connection_credentials_vault IS NOT NULL AND connection_credentials_vault <> ''"
        + (" FOR UPDATE" if lock else "") + ";"
    )
    return cursor.fetchall()


def _connect():
    import psycopg2

    return psycopg2.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))


def check(conn, kms) -> dict:
    counts = {"stored": 0, "current_key": 0, "previous_key": 0, "unreadable": 0, "not_encrypted": 0}
    unreadable = []
    with conn.cursor() as cursor:
        for tenant_id, source_id, value in _rows(cursor):
            counts["stored"] += 1
            if not credential_vault.is_encrypted_envelope(value):
                counts["not_encrypted"] += 1
                unreadable.append(str(source_id))
                continue
            try:
                credential_vault.decrypt_credentials(value, kms)
            except credential_vault.CredentialDecryptionError:
                counts["unreadable"] += 1
                unreadable.append(str(source_id))
                continue
            moved = credential_vault.rewrap_envelope(value, kms)
            counts["current_key" if moved is None else "previous_key"] += 1
    conn.rollback()
    counts["unreadable_source_ids"] = unreadable
    return counts


def rewrap(conn, kms) -> dict:
    """All or nothing: one unreadable credential stops the whole rewrap."""
    moved = 0
    with conn.cursor() as cursor:
        rows = _rows(cursor, lock=True)
        for tenant_id, source_id, value in rows:
            try:
                updated = credential_vault.rewrap_envelope(value, kms)
            except credential_vault.CredentialDecryptionError:
                conn.rollback()
                raise SystemExit(f"Stopped, nothing changed: credential of data source {source_id} can't be opened "
                                 "with the configured keys. Add the key it was stored under to "
                                 "CREDENTIAL_VAULT_PREVIOUS_KEYS and run again.")
            if updated is not None:
                cursor.execute("UPDATE data_sources SET connection_credentials_vault = %s WHERE tenant_id = %s AND source_id = %s;",
                               (updated, tenant_id, source_id))
                moved += 1
    conn.commit()
    return {"stored": len(rows), "rewrapped": moved}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CREDENTIAL_VAULT_MASTER_KEY operations.")
    parser.add_argument("command", choices=["generate", "validate", "check", "rewrap"])
    args = parser.parse_args(argv)

    if args.command == "generate":
        from cryptography.fernet import Fernet

        print(Fernet.generate_key().decode())
        return 0

    problem = credential_vault.master_key_problem(os.getenv("CREDENTIAL_VAULT_MASTER_KEY"))
    if (os.getenv("CREDENTIAL_VAULT_KMS_BACKEND") or "local").lower() == "local" and problem:
        print(f"CREDENTIAL_VAULT_MASTER_KEY {problem}", file=sys.stderr)
        return 1
    try:
        kms = credential_vault.get_default_kms_backend()
    except (RuntimeError, ValueError) as err:
        print(str(err), file=sys.stderr)
        return 1
    if args.command == "validate":
        extra = getattr(kms, "previous_key_count", 0)
        print(f"OK: {kms.name} backend ready" + (f", {extra} previous key(s) accepted for reading" if extra else ""))
        return 0

    conn = _connect()
    try:
        if args.command == "check":
            result = check(conn, kms)
            print(f"stored credentials: {result['stored']} | on the current key: {result['current_key']} | "
                  f"on a previous key: {result['previous_key']} | unreadable: {result['unreadable']} | "
                  f"not encrypted: {result['not_encrypted']}")
            if result["unreadable_source_ids"]:
                print("data sources that can't be opened: " + ", ".join(result["unreadable_source_ids"]))
                return 2
            return 0
        result = rewrap(conn, kms)
        print(f"stored credentials: {result['stored']} | re-wrapped under the current key: {result['rewrapped']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
