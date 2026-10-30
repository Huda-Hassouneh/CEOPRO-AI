"""Native PostgreSQL product and canonical-inventory integration checks."""
import json
import os
import threading
import uuid

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ai import db
from src.ai.core.security import create_access_token
from src.ai.routers import products as product_router
from src.ai.routers.products import create_product, get_product, upsert_inventory

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set")

app = FastAPI()
app.include_router(product_router.router)
client = TestClient(app)


@pytest.fixture
def seeded_tenants():
    admin = psycopg2.connect(DATABASE_URL)
    tenant_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    users = [str(uuid.uuid4()), str(uuid.uuid4())]
    try:
        with admin.cursor() as cursor:
            for i, (tenant_id, user_id) in enumerate(zip(tenant_ids, users)):
                cursor.execute(
                    "INSERT INTO companies (tenant_id,business_name,country_code,primary_currency) "
                    "VALUES (%s,%s,'JO','JOD')",
                    (tenant_id, f"Product test tenant {i}-{tenant_id[:8]}"),
                )
                cursor.execute(
                    "INSERT INTO users (user_id,email,password_hash,full_name,email_verified_at) "
                    "VALUES (%s,%s,'test-hash','Product test user',NOW())",
                    (user_id, f"product-test-{user_id}@example.test"),
                )
                cursor.execute(
                    "INSERT INTO tenant_users (tenant_id,user_id,role_key) VALUES (%s,%s,'owner')",
                    (tenant_id, user_id),
                )
        admin.commit()
        yield tenant_ids, users
    finally:
        admin.rollback()
        admin.close()


def test_restricted_role_crud_is_tenant_scoped_and_preserves_force_rls(seeded_tenants):
    tenants, users = seeded_tenants
    products = []
    for tenant_id, user_id, name in zip(tenants, users, ("Tenant A item", "Tenant B item")):
        conn = db.app_role_connection(tenant_id, user_id)
        try:
            result = create_product(conn, tenant_id, user_id, {"en": name}, None, None, None, 10, None, "JOD")
            conn.commit()
            products.append(result["product_id"])
        finally:
            conn.close()

    conn = db.app_role_connection(tenants[0], users[0])
    try:
        assert get_product(conn, tenants[0], products[1]) is None
        assert upsert_inventory(conn, tenants[0], products[1], stock_quantity=4) is None
        conn.commit()
    finally:
        conn.close()

    admin = psycopg2.connect(DATABASE_URL)
    try:
        with admin.cursor() as cursor:
            cursor.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='ceopro_app'")
            assert cursor.fetchone() == (False, False)
            cursor.execute(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.products'::regclass"
            )
            assert cursor.fetchone() == (True, True)
            cursor.execute(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.inventory'::regclass"
            )
            assert cursor.fetchone() == (True, True)
    finally:
        admin.close()


def test_concurrent_first_manual_stock_writes_cannot_create_duplicate_inventory(seeded_tenants):
    tenant_id, user_id = seeded_tenants[0][0], seeded_tenants[1][0]
    creator = db.app_role_connection(tenant_id, user_id)
    try:
        product = create_product(creator, tenant_id, user_id, {"en": "Concurrent stock"}, None, None, None, 1, None, "JOD")
        creator.commit()
    finally:
        creator.close()

    barrier = threading.Barrier(2)
    errors = []

    def write_stock(value):
        conn = db.app_role_connection(tenant_id, user_id)
        try:
            barrier.wait(timeout=5)
            upsert_inventory(conn, tenant_id, product["product_id"], stock_quantity=value)
            conn.commit()
        except Exception as exc:  # surfaced in the parent test
            conn.rollback()
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=write_stock, args=(value,)) for value in (7, 9)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors

    admin = psycopg2.connect(DATABASE_URL)
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*),MAX(stock_quantity) FROM inventory WHERE tenant_id=%s AND product_id=%s",
                (tenant_id, product["product_id"]),
            )
            assert cursor.fetchone() in ((1, 7), (1, 9))
    finally:
        admin.close()


def test_authenticated_http_stock_edit_and_product_reads_use_restricted_rls(seeded_tenants):
    tenants, users = seeded_tenants
    created = []
    for tenant_id, user_id, name in zip(tenants, users, ("HTTP A", "HTTP B")):
        conn = db.app_role_connection(tenant_id, user_id)
        try:
            product = create_product(conn, tenant_id, user_id, {"en": name}, None, None, None, 4, None, "JOD")
            conn.commit()
            created.append(product["product_id"])
        finally:
            conn.close()

    token, _ = create_access_token(tenants[0], users[0], email_verified=True)
    headers = {"Authorization": f"Bearer {token}"}
    listing = client.get("/products", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    detail = client.get(f"/products/{created[0]}", headers=headers)
    assert detail.status_code == 200 and detail.json()["product_id"] == created[0]
    stock = client.patch(f"/products/{created[0]}/inventory", headers=headers, json={"stock_quantity": 14})
    assert stock.status_code == 200 and stock.json()["stock_quantity"] == 14

    hidden = client.get(f"/products/{created[1]}", headers=headers)
    assert hidden.status_code == 404


def test_tenant_member_cannot_create_products_or_change_canonical_stock(seeded_tenants):
    tenant_id, owner_id = seeded_tenants[0][0], seeded_tenants[1][0]
    product_conn = db.app_role_connection(tenant_id, owner_id)
    try:
        product = create_product(product_conn, tenant_id, owner_id, {"en": "Protected catalog"}, None, None, None, 8, None, "JOD", 6)
        product_conn.commit()
    finally:
        product_conn.close()

    member_id = str(uuid.uuid4())
    admin = psycopg2.connect(DATABASE_URL)
    try:
        with admin.cursor() as cursor:
            cursor.execute(
                "INSERT INTO users (user_id,email,password_hash,full_name,email_verified_at) "
                "VALUES (%s,%s,'test-hash','Product test member',NOW())",
                (member_id, f"product-member-{member_id}@example.test"),
            )
            cursor.execute(
                "INSERT INTO tenant_users (tenant_id,user_id,role_key) VALUES (%s,%s,'staff')",
                (tenant_id, member_id),
            )
        admin.commit()
    finally:
        admin.close()

    token, _ = create_access_token(tenant_id, member_id, email_verified=True)
    headers = {"Authorization": f"Bearer {token}"}
    create = client.post("/products", headers=headers, json={
        "product_name": {"en": "Unauthorized"}, "current_price": 2, "currency": "JOD",
    })
    stock = client.patch(f"/products/{product['product_id']}/inventory", headers=headers, json={"stock_quantity": 99})
    assert create.status_code == 403
    assert stock.status_code == 403

    verify = psycopg2.connect(DATABASE_URL)
    try:
        with verify.cursor() as cursor:
            cursor.execute("SELECT stock_quantity FROM inventory WHERE tenant_id=%s AND product_id=%s", (tenant_id, product["product_id"]))
            assert cursor.fetchone()[0] == 6
            cursor.execute("SELECT COUNT(*) FROM products WHERE tenant_id=%s", (tenant_id,))
            assert cursor.fetchone()[0] == 1
    finally:
        verify.close()
