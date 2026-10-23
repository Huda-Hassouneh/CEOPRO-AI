"""Exercise a disposable populated schema upgrade from migrations 1-102 to 1-103."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import uuid

import psycopg2
from psycopg2 import sql

from src.ai.core.security import hash_password
from scripts import apply_migrations


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "src" / "infrastructure" / "database" / "migrations"


def _subset(paths: list[Path]) -> Path:
    target = Path(tempfile.mkdtemp(prefix="keel-verify-migrations-"))
    for path in paths:
        shutil.copy2(path, target / path.name)
    return target


def main() -> None:
    base_url = os.environ["DATABASE_URL"]
    app_password = os.environ.get("APP_DB_PASSWORD")
    if not app_password:
        raise RuntimeError("APP_DB_PASSWORD is required to preserve the ceopro_app role contract.")
    paths = sorted(MIGRATIONS.glob("*.sql"))
    if len(paths) != 103:
        raise RuntimeError(f"Expected 103 committed SQL migrations, found {len(paths)}.")
    db_name = f"keel_verify_upgrade_{uuid.uuid4().hex[:10]}"
    created = False
    temp_dirs: list[Path] = []
    try:
        admin = psycopg2.connect(base_url.rsplit("/", 1)[0] + "/postgres")
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
        admin.close()
        created = True
        url = base_url.rsplit("/", 1)[0] + f"/{db_name}"
        os.environ["DATABASE_URL"] = url
        old_dir = apply_migrations.MIGRATIONS_DIR
        before_dir = _subset(paths[:102])
        temp_dirs.append(before_dir)
        apply_migrations.MIGRATIONS_DIR = before_dir
        first = apply_migrations.run()
        if len(first) != 102:
            raise RuntimeError(f"Pre-notification migration stage applied {len(first)} files, expected 102.")

        tenant, user, product = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,%s,'JO','JOD')",
                        (tenant, "Populated pre-merge fixture"))
            cur.execute("INSERT INTO users(user_id,email,password_hash,full_name) VALUES(%s,%s,%s,%s)",
                        (user, f"upgrade-{user}@example.test", hash_password("Local-Upgrade-Fixture-Only-99!"), "Upgrade Fixture"))
            cur.execute("INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES(%s,%s,'owner')", (tenant, user))
            cur.execute("INSERT INTO tenant_plan_assignments(tenant_id,plan_key,status,current_period_start,current_period_end,source) "
                        "VALUES(%s,'growth','active',current_date,current_date+30,'manual')", (tenant,))
            cur.execute("INSERT INTO products(product_id,tenant_id,product_name,current_price,currency,source) "
                        "VALUES(%s,%s,'{\"en\":\"Upgrade fixture product\"}'::jsonb,12.50,'JOD','MANUAL')",
                        (product, tenant))
            cur.execute("SELECT count(*) FROM schema_migrations")
            if cur.fetchone()[0] != 102:
                raise RuntimeError("Populated upgrade fixture was not created on the 102-migration schema.")
        last_dir = _subset(paths[102:])
        temp_dirs.append(last_dir)
        apply_migrations.MIGRATIONS_DIR = last_dir
        later = apply_migrations.run()
        if len(later) != 1:
            raise RuntimeError(f"Notification migration stage applied {len(later)} files, expected 1.")
        if apply_migrations.run() != []:
            raise RuntimeError("Merged migration stage rerun was not idempotent.")
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM schema_migrations")
            if cur.fetchone()[0] != 103:
                raise RuntimeError("Upgrade does not contain all 103 migration records.")
            cur.execute("SELECT count(*) FROM companies WHERE tenant_id=%s", (tenant,))
            company_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM tenant_plan_assignments WHERE tenant_id=%s AND plan_key='growth'", (tenant,))
            plan_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM products WHERE tenant_id=%s AND product_id=%s", (tenant, product))
            product_count = cur.fetchone()[0]
            if (company_count, plan_count, product_count) != (1, 1, 1):
                raise RuntimeError("Populated company, subscription assignment, or product was not preserved.")
            cur.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='ceopro_app'")
            restricted_role = cur.fetchone()
            if restricted_role != (False, False):
                raise RuntimeError(f"ceopro_app authority changed unexpectedly: {restricted_role}")
        print("PASS populated migration upgrade: migrations 1-102 applied, company/owner/active Growth assignment/product seeded, 103 applied, 0 applied on repeat; tenant data and restricted-role attributes preserved.")
        apply_migrations.MIGRATIONS_DIR = old_dir
    finally:
        for path in temp_dirs:
            shutil.rmtree(path, ignore_errors=True)
        if created:
            admin = psycopg2.connect(base_url.rsplit("/", 1)[0] + "/postgres")
            admin.autocommit = True
            with admin.cursor() as cur:
                cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s", (db_name,))
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name)))
            admin.close()


if __name__ == "__main__":
    main()
