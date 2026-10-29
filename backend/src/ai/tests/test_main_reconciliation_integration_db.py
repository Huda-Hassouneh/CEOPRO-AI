"""Native reconciliation checks; disposable installer DBs only, no providers."""
import os
import shutil
from contextlib import closing
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn
import pytest

from scripts import apply_migrations as runner


def admin_dsn():
    dsn = os.getenv("AI_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Native disposable database required")
    assert parse_dsn(dsn)["dbname"].startswith("keel_billing_test_")
    return dsn


def test_statistics_function_has_fixed_scope_and_restricted_execution():
    with closing(psycopg2.connect(admin_dsn())) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_get_userbyid(proowner),prosecdef,proconfig,pg_get_functiondef(oid) "
                        "FROM pg_proc WHERE oid='public.refresh_sales_statistics()'::regprocedure")
            owner, definer, config, definition = cur.fetchone()
            assert owner not in ("ceopro_app", "ceopro_billing_setup", "ceopro_billing_webhook", "ceopro_credit_accounting")
            assert definer and "search_path=pg_catalog, pg_temp" in config
            for table in ("invoices", "invoice_items", "transactions"):
                assert f"ANALYZE public.{table};" in definition
                cur.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (table,))
                assert cur.fetchone() == (True, True)
            for role in ("ceopro_app", "ceopro_billing_setup", "ceopro_billing_webhook", "ceopro_credit_accounting"):
                cur.execute("SELECT has_function_privilege(%s,'public.refresh_sales_statistics()','EXECUTE')", (role,))
                assert cur.fetchone()[0] == (role == "ceopro_app")
            cur.execute("SELECT count(*) FROM pg_proc p, LATERAL aclexplode(p.proacl) a "
                        "WHERE p.oid='public.refresh_sales_statistics()'::regprocedure AND a.grantee=0")
            assert cur.fetchone()[0] == 0
    params = parse_dsn(admin_dsn())
    with closing(psycopg2.connect(make_dsn(**{**params, "user": "ceopro_app", "password": os.environ["APP_DB_PASSWORD"]}))) as app:
        with app.cursor() as cur:
            # Temporary objects cannot redirect the privileged command.
            cur.execute("CREATE TEMP TABLE invoices(id int)")
            cur.execute("SELECT public.refresh_sales_statistics()")
            app.commit()
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("ALTER FUNCTION public.refresh_sales_statistics() OWNER TO ceopro_app")
        app.rollback()


def test_upgrade_from_integration_schema_preserves_rows_catalog_and_replays(tmp_path, monkeypatch):
    base = admin_dsn()
    name = "keel_billing_test_reconcile_" + uuid4().hex[:12]
    with closing(psycopg2.connect(base)) as admin:
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    print("Retained reconciliation upgrade database:", name)
    incoming = {"20261031000000_add_invoices_tenant_issue_date_index.sql",
                "20261031010000_add_refresh_sales_statistics.sql",
                "20261116000000_harden_sales_statistics_function.sql"}
    current_dir = runner.MIGRATIONS_DIR
    for path in current_dir.glob("*.sql"):
        if path.name not in incoming:
            shutil.copyfile(path, tmp_path / path.name)
    dsn = make_dsn(base, dbname=name)
    with closing(psycopg2.connect(dsn)) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(runner, "MIGRATIONS_DIR", tmp_path)
            assert len(runner.run(conn)) == len(list(tmp_path.glob("*.sql")))
        with conn.cursor() as cur:
            cur.execute("INSERT INTO companies(business_name,country_code,primary_currency) "
                        "VALUES('SYNTHETIC upgrade preservation','JO','JOD') RETURNING tenant_id")
            tenant = cur.fetchone()[0]
            cur.execute("INSERT INTO invoices(tenant_id,invoice_number,issue_date,payment_status,total_amount,currency) "
                        "VALUES(%s,'SYNTHETIC-UPGRADE',CURRENT_DATE,'PAID',12.34,'JOD')", (tenant,))
        conn.commit()
        tables = ("companies", "invoices", "provider_cost_schedules", "billing_cost_policy",
                  "billing_plan_prices", "tenant_plan_assignments", "usage_ledger", "tenant_credit_balances")
        def snapshot():
            with conn.cursor() as cur:
                result = []
                for table in tables:
                    cur.execute(sql.SQL("SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text")
                                .format(sql.Identifier(table)))
                    result.append(cur.fetchall())
                return result
        before = snapshot()
        assert runner.run(conn) == sorted(incoming)
        assert snapshot() == before
        assert runner.run(conn) == []
        assert snapshot() == before
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.idx_invoices_tenant_issue_date') IS NOT NULL")
            assert cur.fetchone()[0]
