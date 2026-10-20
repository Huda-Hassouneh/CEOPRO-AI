import re
import uuid
from datetime import date, timedelta

from psycopg2 import sql

from scripts import apply_migrations
from src.ai import db


def test_upgrade_preserves_keys_rls_grants_and_allows_new_period(
    assigned, billing_connections
):
    tid, uid = assigned
    original = (
        apply_migrations.MIGRATIONS_DIR
        / "20261020000000_keel_subscriptions_and_credits.sql"
    ).read_text()
    create = re.search(
        r"CREATE TABLE IF NOT EXISTS metered_request_keys \(.*?\n\);",
        original,
        re.DOTALL,
    ).group(0)
    migration = (
        apply_migrations.MIGRATIONS_DIR / "20261024000000_report_request_identity.sql"
    ).read_text()
    schema = "review_upgrade_" + uuid.uuid4().hex
    conn = db.system_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(
                sql.SQL("SET LOCAL search_path TO {}, public").format(
                    sql.Identifier(schema)
                )
            )
            cur.execute(create)
            cur.execute(
                "ALTER TABLE metered_request_keys ENABLE ROW LEVEL SECURITY; ALTER TABLE metered_request_keys FORCE ROW LEVEL SECURITY; GRANT SELECT ON metered_request_keys TO ceopro_app;"
            )
            cur.execute(
                "INSERT INTO metered_request_keys(tenant_id,feature_code,idempotency_key,period_start,actor_user_id) VALUES(%s,'monthly_reports','old-key',%s,%s)",
                (tid, date.today() - timedelta(days=60), uid),
            )
            cur.execute(migration)
            cur.execute(
                "SELECT tenant_id,actor_user_id,request_fingerprint,request_id IS NOT NULL FROM metered_request_keys"
            )
            assert cur.fetchone() == (tid, uid, None, True)
            cur.execute(
                "SELECT relrowsecurity,relforcerowsecurity,has_table_privilege('ceopro_app',oid,'SELECT'),has_table_privilege('ceopro_app',oid,'INSERT') FROM pg_class WHERE oid='metered_request_keys'::regclass"
            )
            assert cur.fetchone() == (True, True, True, False)
            cur.execute(
                "INSERT INTO metered_request_keys(tenant_id,feature_code,idempotency_key,period_start,actor_user_id) VALUES(%s,'monthly_reports','old-key',CURRENT_DATE,%s)",
                (tid, uid),
            )
            cur.execute("SELECT count(*) FROM metered_request_keys")
            assert cur.fetchone()[0] == 2
    finally:
        conn.rollback()
        conn.close()
