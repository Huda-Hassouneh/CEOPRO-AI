"""After a large import the sales tables' planner statistics are refreshed
(migration 20261031010000), so the forecast check the import starts is not
planned on statistics that still describe the company as empty."""
import os
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from src.ai.routers import extraction

CTX = SimpleNamespace(tenant_id="t1", user_id="u1")


def test_the_statistics_refresh_runs_the_owner_function_and_commits():
    conn = MagicMock()
    with patch("src.ai.routers.extraction.db.app_role_connection", return_value=conn):
        extraction._refresh_sales_statistics(CTX)
    conn.cursor.return_value.__enter__.return_value.execute.assert_called_once_with("SELECT refresh_sales_statistics();")
    conn.commit.assert_called_once()
    conn.close.assert_called_once()


def test_a_failed_statistics_refresh_never_fails_the_import():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.execute.side_effect = psycopg2.Error("boom")
    with patch("src.ai.routers.extraction.db.app_role_connection", return_value=conn):
        extraction._refresh_sales_statistics(CTX)  # no exception
    conn.rollback.assert_called_once()
    conn.close.assert_called_once()
    with patch("src.ai.routers.extraction.db.app_role_connection", side_effect=psycopg2.OperationalError("down")):
        extraction._refresh_sales_statistics(CTX)  # no exception


@pytest.mark.skipif(not os.getenv("AI_TEST_DATABASE_URL"), reason="AI_TEST_DATABASE_URL not set")
def test_the_app_role_may_refresh_statistics_only_through_the_function():
    admin = psycopg2.connect(os.environ["AI_TEST_DATABASE_URL"])
    admin.autocommit = True
    with admin.cursor() as cursor:
        cursor.execute("SELECT has_function_privilege('ceopro_app', 'refresh_sales_statistics()', 'EXECUTE'), "
                       "has_function_privilege('public', 'refresh_sales_statistics()', 'EXECUTE');")
        app_may, public_may = cursor.fetchone()
        role = f"stats_probe_{uuid.uuid4().hex[:8]}"
        cursor.execute(f"CREATE ROLE {role};")
        try:
            cursor.execute(f"SET ROLE {role};")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute("SELECT refresh_sales_statistics();")
        finally:
            cursor.execute("RESET ROLE;")
            cursor.execute(f"DROP ROLE {role};")
    admin.close()
    assert app_may and not public_may
