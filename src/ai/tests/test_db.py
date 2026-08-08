from unittest.mock import MagicMock

from src.ai.db import set_tenant_context


def test_set_tenant_context_executes_set_with_tenant_id():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value

    set_tenant_context(conn, "tenant-1")

    cursor.execute.assert_called_once_with("SET app.current_tenant_id = %s;", ("tenant-1",))


def test_set_tenant_context_coerces_non_string_tenant_id():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value

    set_tenant_context(conn, 12345)

    cursor.execute.assert_called_once_with("SET app.current_tenant_id = %s;", ("12345",))
