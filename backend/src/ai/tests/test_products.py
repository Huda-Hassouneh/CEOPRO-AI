"""
Unit tests for the tenant product catalog CRUD - routers/products.py's
/products* endpoints and its own query functions. Same offline-unit/live-
integration split as every other module here: DB fully mocked out,
matching test_main.py's TestClient + patch(..., db.app_role_connection, ...)
convention, adapted to this module's own routers/ location.
"""
import os
from unittest.mock import MagicMock, patch

import time

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.routers import products  # noqa: E402

app = FastAPI()
app.include_router(products.router)
client = TestClient(app)
_SECRET = os.environ["JWT_SECRET"]


def _token(tenant_id="t1", user_id="u1"):
    return jwt.encode({"tenant_id": tenant_id, "user_id": user_id, "exp": int(time.time()) + 3600}, _SECRET, algorithm="HS256")


def _auth():
    return {"Authorization": f"Bearer {_token()}"}


# ---------------------------------------------------------------------------
# Endpoint-level tests (routers/products.py) - mock the module's own query
# functions, assert on the HTTP contract and on exactly what the endpoint
# hands down to them.
# ---------------------------------------------------------------------------

def test_list_products_requires_auth():
    response = client.get("/products")
    assert response.status_code == 401


def test_list_products_returns_empty_result():
    fake_conn = MagicMock()
    empty = {"products": [], "total": 0, "limit": 50, "offset": 0}
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products.list_products", return_value=empty) as mock_list:
        response = client.get("/products", headers=_auth())

    assert response.status_code == 200
    assert response.json() == empty
    fake_conn.commit.assert_called_once()
    mock_list.assert_called_once_with(fake_conn, "t1", limit=50, offset=0, search=None)


def test_list_products_returns_results_with_stock_and_resolved_names():
    fake_conn = MagicMock()
    fake_result = {
        "products": [
            {"product_id": "p1", "product_name": "Widget", "brand": None, "category": "Electronics",
             "current_price": 10.0, "cost_price": 6.0, "currency": "JOD", "source": "MANUAL",
             "stock_quantity": 25},
            {"product_id": "p2", "product_name": "Gadget", "brand": None, "category": None,
             "current_price": 20.0, "cost_price": None, "currency": "JOD", "source": "IMPORTED",
             "stock_quantity": None},
        ],
        "total": 2, "limit": 50, "offset": 0,
    }
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products.list_products", return_value=fake_result):
        response = client.get("/products", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["products"][0]["stock_quantity"] == 25
    assert body["products"][1]["stock_quantity"] is None  # no inventory row yet - never fabricated as 0


def test_list_products_passes_search_and_pagination_through():
    fake_conn = MagicMock()
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products.list_products", return_value={"products": [], "total": 0, "limit": 5, "offset": 10}) as mock_list:
        response = client.get("/products", params={"search": "widget", "limit": 5, "offset": 10}, headers=_auth())

    assert response.status_code == 200
    mock_list.assert_called_once_with(fake_conn, "t1", limit=5, offset=10, search="widget")


def test_list_products_rejects_an_out_of_bounds_limit():
    response = client.get("/products", params={"limit": 0}, headers=_auth())
    assert response.status_code == 422

    response = client.get("/products", params={"limit": 1001}, headers=_auth())
    assert response.status_code == 422


def test_list_products_accepts_the_whole_catalog_fetch_the_frontend_actually_sends():
    """
    forecastingApi.js and marketIntelligenceApi.js both fetch a tenant's
    entire product catalog in one request (PRODUCTS_LIMIT = 500) to run
    Demand Forecast/Market Intelligence analysis across every product,
    not a paginated subset - a real bug (found via a live Playwright
    audit of /demand and /market) had MAX_LIMIT capped at 200, so this
    exact request 422'd on every real page load, surfacing to the user
    as "Demand prediction unavailable"/"Market intelligence unavailable"
    for every account, regardless of how many products it actually had.
    """
    fake_conn = MagicMock()
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products.list_products", return_value={"products": [], "total": 0, "limit": 500, "offset": 0}):
        response = client.get("/products", params={"limit": 500}, headers=_auth())

    assert response.status_code == 200


def test_get_product_requires_auth():
    response = client.get("/products/p1")
    assert response.status_code == 401


def test_get_product_returns_full_detail_shape():
    fake_conn = MagicMock()
    fake_result = {
        "product_id": "p1", "product_name": {"en": "Widget", "ar": "ودجت"}, "brand": None,
        "category": {"en": "Electronics"}, "description": None, "current_price": 10.0,
        "cost_price": 6.0, "currency": "JOD", "source": "MANUAL",
        "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00",
        "inventory": {"stock_quantity": 25, "reorder_level": 10, "safety_stock": 5,
                       "warehouse_location": None, "updated_at": "2026-09-01T00:00:00+00:00"},
    }
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products.get_product", return_value=fake_result) as mock_get:
        response = client.get("/products/p1", headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    mock_get.assert_called_once_with(fake_conn, "t1", "p1")


def test_get_product_returns_404_for_missing_or_deleted_product():
    fake_conn = MagicMock()
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products.get_product", return_value=None):
        response = client.get("/products/missing", headers=_auth())

    assert response.status_code == 404
    fake_conn.rollback.assert_called_once()


def test_create_product_requires_auth():
    response = client.post("/products", json={"product_name": {"en": "Widget"}, "current_price": 10.0, "currency": "JOD"})
    assert response.status_code == 401


def test_create_product_rejects_missing_en_key():
    """product_name with only 'ar' (no 'en') must be rejected - every
    existing read path resolves display name via product_name->>'en' first."""
    response = client.post(
        "/products",
        json={"product_name": {"ar": "ودجت"}, "current_price": 10.0, "currency": "JOD"},
        headers=_auth(),
    )
    assert response.status_code == 422


def test_create_product_rejects_empty_en_value():
    response = client.post(
        "/products",
        json={"product_name": {"en": "   "}, "current_price": 10.0, "currency": "JOD"},
        headers=_auth(),
    )
    assert response.status_code == 422


def test_create_product_rejects_missing_product_name():
    response = client.post("/products", json={"current_price": 10.0, "currency": "JOD"}, headers=_auth())
    assert response.status_code == 422


def test_create_product_rejects_negative_current_price():
    response = client.post(
        "/products",
        json={"product_name": {"en": "Widget"}, "current_price": -1.0, "currency": "JOD"},
        headers=_auth(),
    )
    assert response.status_code == 422


def test_create_product_rejects_negative_cost_price():
    response = client.post(
        "/products",
        json={"product_name": {"en": "Widget"}, "current_price": 10.0, "cost_price": -1.0, "currency": "JOD"},
        headers=_auth(),
    )
    assert response.status_code == 422


def test_create_product_rejects_malformed_currency():
    response = client.post(
        "/products",
        json={"product_name": {"en": "Widget"}, "current_price": 10.0, "currency": "jod"},
        headers=_auth(),
    )
    assert response.status_code == 422


def test_create_product_calls_with_manual_semantics_and_returns_result():
    """The real contract: the endpoint must hand the tenant/user context
    and every body field straight through to create_product(), which is
    the function actually responsible for writing source='MANUAL'
    (asserted directly against the real SQL in the query-layer tests
    below) - this test only pins the endpoint's own wiring."""
    fake_conn = MagicMock()
    fake_result = {"product_id": "new-1", "product_name": {"en": "Widget"}, "source": "MANUAL"}
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products._require_catalog_admin"), \
         patch("src.ai.routers.products.create_product", return_value=fake_result) as mock_create, \
         patch("src.ai.routers.products._publish_discovery_request"):
        response = client.post(
            "/products",
            json={
                "product_name": {"en": "Widget", "ar": "ودجت"}, "brand": {"en": "Acme"},
                "current_price": 10.0, "cost_price": 6.0, "currency": "JOD",
                "initial_stock_quantity": 25,
            },
            headers=_auth(),
        )

    assert response.status_code == 200
    assert response.json() == fake_result
    fake_conn.commit.assert_called_once()
    mock_create.assert_called_once_with(
        fake_conn, "t1", "u1", {"en": "Widget", "ar": "ودجت"}, {"en": "Acme"}, None, None,
        10.0, 6.0, "JOD", 25, None,
    )


def test_create_product_defaults_initial_stock_to_none_when_omitted():
    fake_conn = MagicMock()
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products._require_catalog_admin"), \
         patch("src.ai.routers.products.create_product", return_value={}) as mock_create, \
         patch("src.ai.routers.products._publish_discovery_request"):
        client.post(
            "/products",
            json={"product_name": {"en": "Widget"}, "current_price": 10.0, "currency": "JOD"},
            headers=_auth(),
        )

    assert mock_create.call_args.args[-1] is None  # initial_stock_quantity


def test_update_product_requires_auth():
    response = client.patch("/products/p1", json={"current_price": 12.0})
    assert response.status_code == 401


def test_update_product_sends_only_provided_fields():
    """Partial update: a field the caller never sent must not appear in
    the dict handed to update_product() at all - distinguishing 'omitted'
    from 'explicitly null'."""
    fake_conn = MagicMock()
    fake_result = {"product_id": "p1", "current_price": 12.0}
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products._require_catalog_admin"), \
         patch("src.ai.routers.products.update_product", return_value=fake_result) as mock_update:
        response = client.patch("/products/p1", json={"current_price": 12.0}, headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    mock_update.assert_called_once_with(fake_conn, "t1", "u1", "p1", {"current_price": 12.0})


def test_update_product_rejects_negative_price():
    response = client.patch("/products/p1", json={"current_price": -5.0}, headers=_auth())
    assert response.status_code == 422


def test_update_product_rejects_product_name_without_en_key():
    response = client.patch("/products/p1", json={"product_name": {"ar": "x"}}, headers=_auth())
    assert response.status_code == 422


def test_update_product_returns_404_for_missing_or_deleted_product():
    fake_conn = MagicMock()
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products._require_catalog_admin"), \
         patch("src.ai.routers.products.update_product", return_value=None):
        response = client.patch("/products/missing", json={"current_price": 12.0}, headers=_auth())

    assert response.status_code == 404
    fake_conn.rollback.assert_called_once()


def test_delete_product_requires_auth():
    response = client.delete("/products/p1")
    assert response.status_code == 401


def test_delete_product_soft_deletes_and_returns_ok():
    fake_conn = MagicMock()
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products._require_catalog_admin"), \
         patch("src.ai.routers.products.delete_product", return_value=True) as mock_delete:
        response = client.delete("/products/p1", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    fake_conn.commit.assert_called_once()
    mock_delete.assert_called_once_with(fake_conn, "t1", "p1")


def test_delete_product_returns_404_for_missing_or_already_deleted_product():
    fake_conn = MagicMock()
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products._require_catalog_admin"), \
         patch("src.ai.routers.products.delete_product", return_value=False):
        response = client.delete("/products/missing", headers=_auth())

    assert response.status_code == 404
    fake_conn.rollback.assert_called_once()


def test_update_inventory_requires_auth():
    response = client.patch("/products/p1/inventory", json={"stock_quantity": 5})
    assert response.status_code == 401


def test_update_inventory_upserts_and_returns_the_row():
    fake_conn = MagicMock()
    fake_result = {"stock_quantity": 5, "reorder_level": 10, "safety_stock": 5,
                    "warehouse_location": None, "updated_at": "2026-09-01T00:00:00+00:00"}
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products._require_catalog_admin"), \
         patch("src.ai.routers.products.upsert_inventory", return_value=fake_result) as mock_upsert:
        response = client.patch("/products/p1/inventory", json={"stock_quantity": 5}, headers=_auth())

    assert response.status_code == 200
    assert response.json() == fake_result
    mock_upsert.assert_called_once_with(fake_conn, "t1", "p1", 5, None, None)


def test_update_inventory_rejects_negative_stock_quantity():
    response = client.patch("/products/p1/inventory", json={"stock_quantity": -1}, headers=_auth())
    assert response.status_code == 422


def test_canonical_inventory_preserves_fractional_quantities():
    fake_conn = MagicMock()
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products._require_catalog_admin"), \
         patch("src.ai.routers.products.upsert_inventory", return_value={"stock_quantity": 1.2345}) as mock_upsert:
        response = client.patch("/products/p1/inventory", json={"stock_quantity": 1.2345}, headers=_auth())
    assert response.status_code == 200
    assert str(mock_upsert.call_args.args[3]) == "1.2345"
    assert client.patch("/products/p1/inventory", json={"stock_quantity": 1.23456}, headers=_auth()).status_code == 422


def test_catalog_mutations_require_current_owner_or_admin_membership():
    member_conn = MagicMock()
    member_conn.cursor.return_value.__enter__.return_value.fetchone.return_value = ("staff",)
    with pytest.raises(HTTPException) as denied:
        products._require_catalog_admin(member_conn, "t1", "u1")
    assert denied.value.status_code == 403
    executed_sql = member_conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
    assert "FOR SHARE" in executed_sql
    assert "role_key IN" not in executed_sql  # role is checked against a fixed code set in Python


def test_discovery_dependency_failure_does_not_report_committed_product_create_as_failed(caplog):
    # Discovery is a post-commit notification. An absent optional extraction
    # dependency must not turn a persisted product create into an apparent
    # failure that could duplicate on client retry.
    with patch("src.ai.routers.products.importlib.import_module", side_effect=ImportError("optional parser unavailable")):
        products._publish_discovery_request("tenant-a")
    assert "Could not enqueue product discovery" in caplog.text


def test_update_inventory_returns_404_for_missing_or_deleted_product():
    fake_conn = MagicMock()
    with patch("src.ai.routers.products.db.app_role_connection", return_value=fake_conn), \
         patch("src.ai.routers.products._require_catalog_admin"), \
         patch("src.ai.routers.products.upsert_inventory", return_value=None):
        response = client.patch("/products/missing/inventory", json={"stock_quantity": 5}, headers=_auth())

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Query-layer tests - assert on the real SQL/params these functions send,
# with conn/cursor mocked out (same MagicMock-cursor convention used
# throughout this package's offline unit tests).
# ---------------------------------------------------------------------------

def _cursor_returning(fetchone_values=None, fetchall_value=None):
    """Builds a MagicMock cursor whose fetchone()/fetchall() return the
    given values in sequence (fetchone) or a fixed list (fetchall), and
    that works as a context manager (conn.cursor() as cursor)."""
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    if fetchone_values is not None:
        cursor.fetchone.side_effect = list(fetchone_values)
    if fetchall_value is not None:
        cursor.fetchall.return_value = fetchall_value
    return cursor


def test_query_list_products_builds_search_predicate_only_when_given():
    """list_products() uses a single cursor (one `with conn.cursor()`
    block) for both the COUNT and the paginated SELECT - two execute()
    calls on the same cursor, mirrored here via call_args_list."""
    conn = MagicMock()
    cursor = _cursor_returning(fetchone_values=[(0,)], fetchall_value=[])
    conn.cursor.return_value = cursor

    products.list_products(conn, "t1", limit=50, offset=0, search=None)

    count_sql = cursor.execute.call_args_list[0].args[0]
    assert "ILIKE" not in count_sql
    list_sql, list_params = cursor.execute.call_args_list[1].args
    assert "ILIKE" not in list_sql
    assert list_params == ["t1", 50, 0]


def test_query_list_products_total_reflects_the_real_count_not_the_page_size():
    """
    The frontend's Products page now displays this total directly
    ("Total Products: N") specifically because it must NOT be derived by
    counting the rows a paginated request happens to return - a truncated
    page must not look like the whole catalog. list_products() runs the
    COUNT(*) as its own separate query (no LIMIT/OFFSET applied to it at
    all - see the SQL text asserted below), so total can, and here does,
    exceed the number of rows the paginated SELECT actually returns.
    """
    conn = MagicMock()
    # COUNT(*) reports 137 real rows; the paginated SELECT (limit=2) only
    # returns 2 of them - total must still read 137, not 2.
    cursor = _cursor_returning(
        fetchone_values=[(137,)],
        fetchall_value=[
            ("p1", "Widget", None, None, 10.0, None, "JOD", "MANUAL", None, None,1),
            ("p2", "Gadget", None, None, 20.0, None, "JOD", "IMPORTED", None, None,1),
        ],
    )
    conn.cursor.return_value = cursor

    result = products.list_products(conn, "t1", limit=2, offset=0, search=None)

    count_sql = cursor.execute.call_args_list[0].args[0]
    assert "LIMIT" not in count_sql and "OFFSET" not in count_sql
    assert result["total"] == 137
    assert len(result["products"]) == 2


def test_query_list_products_searches_every_name_language_brand_and_category():
    conn = MagicMock()
    cursor = _cursor_returning(fetchone_values=[(1,)], fetchall_value=[])
    conn.cursor.return_value = cursor

    products.list_products(conn, "t1", limit=50, offset=0, search="50%_off")

    list_sql, list_params = cursor.execute.call_args_list[1].args
    for column in ("p.product_name", "p.brand", "p.category"):
        assert f"jsonb_typeof({column})" in list_sql
    assert list_sql.count("jsonb_each_text") == 3
    # LIKE wildcards typed by the user are matched literally.
    assert list_params == ["t1", *([r"%50\%\_off%"]*4), 50, 0]
    assert "p.sku ILIKE %s" in list_sql


def test_query_get_product_returns_none_when_missing():
    conn = MagicMock()
    cursor = _cursor_returning(fetchone_values=[None])
    conn.cursor.return_value = cursor

    assert products.get_product(conn, "t1", "missing") is None


def test_query_get_product_filters_soft_deleted_rows():
    conn = MagicMock()
    cursor = _cursor_returning(fetchone_values=[None])
    conn.cursor.return_value = cursor

    products.get_product(conn, "t1", "p1")

    sql = cursor.execute.call_args.args[0]
    assert "deleted_at IS NULL" in sql


def test_query_create_product_always_writes_manual_source():
    """The load-bearing guarantee: this router must never be able to
    write source='IMPORTED' regardless of any caller input, since
    ProductCreateRequest doesn't even expose a `source` field - the SQL
    itself hardcodes 'MANUAL'.

    create_product() opens one cursor for the products+inventory INSERTs
    (a single `with conn.cursor()` block, two execute() calls) and then
    calls get_product() for its return value, which opens a second
    cursor (product SELECT + inventory SELECT) - two conn.cursor() calls
    total, mirrored here as insert_cursor/get_cursor."""
    conn = MagicMock()
    insert_cursor = _cursor_returning(fetchone_values=[("new-product-id",)])
    get_cursor = _cursor_returning(fetchone_values=[
        ("new-product-id", {"en": "Widget"}, None, None, None, 10.0, None, "JOD", "MANUAL", None, None, None, None, 1),
        None,
    ])
    conn.cursor.side_effect = [insert_cursor, get_cursor]

    products.create_product(
        conn, "t1", "u1", {"en": "Widget"}, None, None, None, 10.0, None, "JOD", 25,
    )

    insert_sql = insert_cursor.execute.call_args_list[0].args[0]
    assert "'MANUAL'" in insert_sql
    assert "IMPORTED" not in insert_sql

    inventory_sql, inventory_params = insert_cursor.execute.call_args_list[1].args
    assert "INSERT INTO inventory" in inventory_sql
    assert inventory_params == ("t1", "new-product-id", 25)


def test_query_create_product_leaves_stock_untracked_when_omitted():
    """No starting stock = stock not tracked (services, made-to-order) - not
    a fabricated zero-stock row that blocks every sale."""
    conn = MagicMock()
    insert_cursor = _cursor_returning(fetchone_values=[("new-product-id",)])
    get_cursor = _cursor_returning(fetchone_values=[
        ("new-product-id", {"en": "Widget"}, None, None, None, 10.0, None, "JOD", "MANUAL", None, None, None, None, 1),
        None,
    ])
    conn.cursor.side_effect = [insert_cursor, get_cursor]

    products.create_product(conn, "t1", "u1", {"en": "Widget"}, None, None, None, 10.0, None, "JOD", None)

    assert len(insert_cursor.execute.call_args_list) == 1  # the product insert only
    assert "inventory" not in insert_cursor.execute.call_args_list[0].args[0]


def test_query_update_product_rejects_unknown_fields():
    conn = MagicMock()
    with pytest.raises(products.ProductValidationError):
        products.update_product(conn, "t1", "u1", "p1", {"source": "IMPORTED"})
    conn.cursor.assert_not_called()  # rejected before any query runs


def test_query_update_product_builds_set_clause_only_from_whitelisted_columns():
    conn = MagicMock()
    update_cursor = _cursor_returning(fetchone_values=[("p1",)])
    get_cursor = _cursor_returning(fetchone_values=[
        ("p1", {"en": "New Name"}, None, None, None, 12.0, None, "JOD", "MANUAL", None, None, None, None, 1), None,
    ])
    conn.cursor.side_effect = [update_cursor, get_cursor]

    products.update_product(conn, "t1", "u1", "p1", {"product_name": {"en": "New Name"}, "current_price": 12.0})

    sql, params = update_cursor.execute.call_args.args
    assert "product_name = %s::jsonb" in sql
    assert "current_price = %s" in sql
    assert "source" not in sql.split("SET")[1].split("WHERE")[0]
    assert "deleted_at IS NULL" in sql


def test_query_delete_product_never_issues_a_real_delete():
    conn = MagicMock()
    cursor = _cursor_returning(fetchone_values=[("p1",)])
    conn.cursor.return_value = cursor

    result = products.delete_product(conn, "t1", "p1")

    sql = cursor.execute.call_args.args[0]
    assert result is True
    assert sql.strip().upper().startswith("UPDATE PRODUCTS")
    assert "DELETE FROM" not in sql.upper()
    assert "deleted_at = NOW()" in sql
    assert "deleted_at IS NULL" in sql  # guards against re-deleting an already-deleted row


def test_query_delete_product_returns_false_when_nothing_matched():
    conn = MagicMock()
    cursor = _cursor_returning(fetchone_values=[None])
    conn.cursor.return_value = cursor

    assert products.delete_product(conn, "t1", "missing") is False


def test_query_upsert_inventory_returns_none_for_missing_product():
    conn = MagicMock()
    cursor = _cursor_returning(fetchone_values=[None])
    conn.cursor.return_value = cursor

    assert products.upsert_inventory(conn, "t1", "missing", stock_quantity=5) is None


def test_query_upsert_inventory_inserts_when_no_row_exists_yet():
    conn = MagicMock()
    cursor = _cursor_returning(fetchone_values=[
        (1,),  # product exists check
        None,  # no existing inventory row
        (5, 10, 5, None, None),  # RETURNING from the INSERT
    ])
    conn.cursor.return_value = cursor

    result = products.upsert_inventory(conn, "t1", "p1", stock_quantity=5)

    insert_call = cursor.execute.call_args_list[-1]
    assert "INSERT INTO inventory" in insert_call.args[0]
    assert result["stock_quantity"] == 5
    assert result["reorder_level"] == 10
    assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]


def test_query_upsert_inventory_updates_only_provided_fields_when_row_exists():
    conn = MagicMock()
    cursor = _cursor_returning(fetchone_values=[
        (1,),  # product exists check
        ("inv-1",),  # existing inventory row id
        (7, 10, 5, None, None),  # RETURNING from the UPDATE
    ])
    conn.cursor.return_value = cursor

    result = products.upsert_inventory(conn, "t1", "p1", stock_quantity=7)

    update_call = cursor.execute.call_args_list[-1]
    sql, params = update_call.args
    assert "UPDATE inventory SET stock_quantity = %s" in sql
    assert "reorder_level" not in sql.split("SET")[1].split("WHERE")[0]
    assert params == [7, "inv-1"]
    assert result["stock_quantity"] == 7


# ---- barcode (EAN/UPC/GTIN) ---------------------------------------------------------------

def test_barcode_check_digit_validation():
    from src.ai.core.barcode import normalize_barcode
    assert normalize_barcode("3017620422003") == "3017620422003"          # EAN-13
    assert normalize_barcode("3017 6204-22003") == "3017620422003"        # spaces and hyphens are removed
    assert normalize_barcode("036000291452") == "036000291452"            # UPC-A
    assert normalize_barcode("96385074") == "96385074"                    # EAN-8
    assert normalize_barcode(None) is None and normalize_barcode("  ") is None
    for bad in ("3017620422004", "12345", "30176204220AB", "0360002914521"):
        try:
            normalize_barcode(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have been refused")


def test_create_and_update_refuse_a_bad_barcode_with_a_422():
    body = {"product_name": {"en": "Widget"}, "current_price": 1, "currency": "JOD", "barcode": "3017620422004"}
    assert client.post("/products", json=body, headers=_auth()).status_code == 422
    assert client.patch("/products/p1", json={"barcode": "123"}, headers=_auth()).status_code == 422


def test_create_passes_a_normalized_barcode_through():
    with patch("src.ai.routers.products.db.app_role_connection", return_value=MagicMock()), \
         patch("src.ai.routers.products._require_catalog_admin"), \
         patch("src.ai.routers.products._publish_discovery_request"), \
         patch("src.ai.routers.products.create_product", return_value={"product_id": "n"}) as mock_create:
        response = client.post(
            "/products", headers=_auth(),
            json={"product_name": {"en": "Widget"}, "current_price": 1, "currency": "JOD", "barcode": "3017 6204 22003"},
        )
    assert response.status_code == 200
    assert mock_create.call_args.args[-1] == "3017620422003"


def test_query_create_product_stores_the_barcode_in_metadata_without_touching_other_keys():
    conn = MagicMock()
    insert_cursor = _cursor_returning(fetchone_values=[("new-id",)])
    get_cursor = _cursor_returning(fetchone_values=[
        ("new-id", {"en": "Widget"}, None, None, None, 10.0, None, "JOD", "MANUAL", None, None, "3017620422003", None, 1), None,
    ])
    conn.cursor.side_effect = [insert_cursor, get_cursor]
    result = products.create_product(conn, "t1", "u1", {"en": "Widget"}, None, None, None, 10.0, None, "JOD", None, "3017620422003")
    sql, params = insert_cursor.execute.call_args_list[0].args
    assert "metadata" in sql and '"barcode": "3017620422003"' in params[8]
    assert result["barcode"] == "3017620422003"
    conn.cursor.side_effect = [_cursor_returning(fetchone_values=[("n2",)]), _cursor_returning(fetchone_values=[
        ("n2", {"en": "W"}, None, None, None, 1.0, None, "JOD", "MANUAL", None, None, None, None, 1), None])]
    products.create_product(conn, "t1", "u1", {"en": "W"}, None, None, None, 1.0, None, "JOD", None)
    assert conn.cursor.call_count == 4


def test_query_update_product_sets_and_clears_the_barcode_key_only():
    for value, expected_fragment in (("3017620422003", "|| jsonb_build_object('barcode'"), (None, "- 'barcode'")):
        conn = MagicMock()
        update_cursor = _cursor_returning(fetchone_values=[("p1",)])
        get_cursor = _cursor_returning(fetchone_values=[
            ("p1", {"en": "W"}, None, None, None, 1.0, None, "JOD", "MANUAL", None, None, value, None, 1), None])
        conn.cursor.side_effect = [update_cursor, get_cursor]
        products.update_product(conn, "t1", "u1", "p1", {"barcode": value})
        sql, params = update_cursor.execute.call_args.args
        assert expected_fragment in sql and "metadata = COALESCE(metadata" in sql
        assert ("3017620422003" in params) is (value is not None)
