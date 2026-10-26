"""
KEEL - Tenant Product Catalog CRUD.

Before this router existed, the only product-related endpoints were
read-only and dashboard-oriented (dashboard/inventory.py, dashboard/
inventory_recommendations.py, etc.) - nothing let a tenant list/create/
update/delete a row in their own `products` table directly. This is that
real write path, for the catalog itself (not sales, not extraction/
upload's bulk-import path).

Every handler opens its connection via db.app_role_connection(tenant_id,
user_id) - see that module's own docstring for why: it is the one call
site that authenticates as the restricted ceopro_app role (not the
superuser ceopro_admin) and sets app.current_tenant_id/app.current_user_id
for the transaction, which is what makes every RLS policy below actually
scope to the caller's own tenant. The explicit `tenant_id = %s` /
`deleted_at IS NULL` filters in every query here are deliberately
redundant with RLS (select_products_isolated already does both for
SELECT) - defense in depth, and UPDATE/DELETE policies do NOT filter
deleted_at, so an explicit check is the only thing standing between a
caller and re-"deleting" or editing an already soft-deleted row.

No `router = APIRouter(prefix="/products", ...)` - matching competitors.py's
own precedent of avoiding a prefix + an empty-string route path, kept
consistent here rather than reintroducing that ambiguity.

product_name/brand/category/description are all JSONB (Final_schema.sql)
- this codebase's i18n convention, a dict of locale code -> string, e.g.
{"en": "Widget", "ar": "..."}. Every existing read path (dashboard/
search.py, dashboard/inventory_recommendations.py) resolves a single
display string via COALESCE(product_name->>'en', product_name->>'ar',
product_name::text) - mirrored here for list/get so this router's own
read shape stays consistent with the rest of the API, rather than ever
handing a raw JSONB blob back to a list view.

source is always written as 'MANUAL' by create_product() (chk_product_
source: 'MANUAL' or 'IMPORTED') - 'IMPORTED' is reserved for extraction/
promotion.py's file-upload pipeline and is never written from here. It is
also never accepted as an update field: an update through this router can
only ever adjust a MANUAL product's own fields, never relabel how a row
was created.

DELETE is always a soft-delete (`deleted_at = NOW()`), matching this
schema's established convention - a real `DELETE FROM products` would
violate fk_invoice_items_product's ON DELETE RESTRICT the moment the
product had ever been sold, and would destroy the audit trail
product_price_history's trigger has already been recording.

Inventory is a genuinely separate table (`inventory`, product_id FK, its
own stock_quantity/reorder_level/safety_stock) with no DB-level
uniqueness on (tenant_id, product_id) - only (tenant_id, inventory_id).
create_product() inserts an inventory row only when the owner gives a
starting stock. No row means "stock is not tracked for this product" -
services (a haircut, a consulting hour), made-to-order and digital
products. It used to insert a zero-stock row for every new product, so a
services business could never record a sale ("Only 0 unit(s) in stock")
and every service counted as out of stock on the dashboard.
upsert_inventory() is the only other writer of that row in this router
(select-then-insert-or-update, since there is no DB constraint to
ON CONFLICT against) - as long as it and create_product() remain the only
two write paths into `inventory`, at most one row per product ever
exists; that is an application-level guarantee, not one this schema
itself enforces, flagged here rather than silently assumed.
"""
import importlib
import json
import logging
from decimal import Decimal
from typing import Dict, Optional

from src.ai.core.barcode import normalize_barcode
from src.ai.extraction.product_identity import normalize_sku, resolve_reference
from src.ai.core import text_search
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from src.ai.core.quantities import as_quantity
from src.ai import db
from src.ai.core.security import TenantContext, get_tenant_context
from src.ai.core import usage

router = APIRouter(tags=["products"])
logger = logging.getLogger(__name__)


def _publish_discovery_request(tenant_id: str) -> None:
    """Load the extraction subsystem only after product creation.

    The discovery queue helper lives beside file-ingestion routes, whose
    imports include PDF/XLSX parsers. Eagerly importing that router here made
    a basic Products API depend on every extraction-only package at startup.
    Keep the same queue contract while deferring that unrelated dependency
    graph until the post-commit notification is actually sent.
    """
    try:
        extraction = importlib.import_module("src.ai.routers.extraction")
        extraction._publish_discovery_request(tenant_id)
    except Exception:
        # Product creation is already committed before this best-effort
        # notification. Returning an error now would invite a duplicate
        # product retry when an optional parser/Redis dependency is down.
        logger.warning("Could not enqueue product discovery for tenant=%s", tenant_id, exc_info=True)

DEFAULT_LIMIT = 50
# Matches shared/catalog/planCatalog.js's own documented per-tenant product
# ceiling (every plan's `limits.products` tops out at 1000) - the Market
# Intelligence and Demand Forecast pages both intentionally fetch a
# tenant's entire catalog in one request (forecastingApi.js/
# marketIntelligenceApi.js's own PRODUCTS_LIMIT = 500) to run their
# analysis across every product, not a paginated subset. The previous
# MAX_LIMIT=200 silently broke both pages for any real account
# (rejecting the request with a 422, which the frontend correctly but
# unhelpfully renders as "market intelligence unavailable") - reproduced
# directly: GET /products?limit=500 -> 422 on every /market and /demand
# page load.
MAX_LIMIT = 1000
_CATALOG_ADMIN_ROLES = {"owner", "admin"}


def _require_catalog_admin(conn, tenant_id: str, user_id: str) -> None:
    """Require the caller's current tenant Owner/Admin role for mutations.

    Roles are read from the active membership inside this request's
    restricted tenant transaction; no JWT role claim can grant write access.
    FOR SHARE keeps a concurrent membership role/removal change from racing
    this mutation before its transaction commits.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT role_key FROM tenant_users WHERE tenant_id=%s AND user_id=%s "
            "AND removed_at IS NULL AND platform_suspended_at IS NULL FOR SHARE;",
            (tenant_id, user_id),
        )
        row = cursor.fetchone()
    if not row or row[0] not in _CATALOG_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only workspace owners and admins can manage products or inventory.")

# Locale-resolution expression matching the read-side convention already
# established across dashboard/search.py, dashboard/inventory_recommendations.py -
# "en" first, then "ar", then a raw text fallback so a product with neither
# key still renders as *something* rather than NULL.
_NAME_EXPR = "localized_text(p.product_name)"
_BRAND_EXPR = "COALESCE(p.brand->>'en', p.brand->>'ar', p.brand::text)"
_CATEGORY_EXPR = "localized_text(p.category)"

# Fixed, hardcoded whitelist of real `products` columns update_product() is
# allowed to touch - never derived from caller input, so a SET clause built
# from this can never interpolate an attacker-chosen column name. Every
# value is still sent as a real parameterized query parameter.
_UPDATABLE_JSONB_COLUMNS = ("product_name", "brand", "category", "description")
_UPDATABLE_SCALAR_COLUMNS = ("current_price", "cost_price", "currency", "sku")
# "barcode" is not a column: it lives in products.metadata->>'barcode' and is written
# through its own branch in update_product() below.
_UPDATABLE_COLUMNS = frozenset(_UPDATABLE_JSONB_COLUMNS) | frozenset(_UPDATABLE_SCALAR_COLUMNS) | {"barcode"}


class ProductValidationError(Exception):
    """Raised for a caller-supplied field this module refuses to write -
    e.g. a field outside _UPDATABLE_COLUMNS."""


# --- request models --------------------------------------------------------

class ProductCreateRequest(BaseModel):
    """
    POST /products - creates a MANUAL product in the tenant's own catalog
    (create_product() always writes source='MANUAL'; 'IMPORTED' is
    reserved for extraction/promotion.py's file-upload pipeline and is
    never reachable from this endpoint).

    product_name must carry a non-empty "en" key: every existing read
    path in this codebase resolves display name via COALESCE(product_name
    ->>'en', product_name->>'ar', ...) - a product created with no "en"
    key would still be legal at the DB layer but would only ever display
    through that fallback everywhere else in the app, so this is rejected
    up front (422) instead.

    current_price/cost_price >= 0 is enforced here too, not just by the
    DB's own CHECK constraints - a fast, honest 422 instead of a raw
    IntegrityError surfacing as an unhandled 500. currency must be a
    3-letter uppercase code, matching products.currency's own CHECK.
    """
    product_name: Dict[str, str]
    brand: Optional[Dict[str, str]] = None
    category: Optional[Dict[str, str]] = None
    description: Optional[Dict[str, str]] = None
    current_price: float = Field(..., ge=0)
    cost_price: Optional[float] = Field(default=None, ge=0)
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    # Canonical quantities follow the approved NUMERIC(14,4) schema.
    initial_stock_quantity: Optional[Decimal] = Field(default=None, ge=0, le=1_000_000_000, max_digits=14, decimal_places=4)
    # EAN/UPC/GTIN. Optional; checked (length + GS1 check digit) and stored digits-only.
    sku: Optional[str] = None

    @field_validator("sku")
    @classmethod
    def _sku_is_valid(cls, value):
        return normalize_sku(value)

    barcode: Optional[str] = None

    @field_validator("barcode")
    @classmethod
    def _barcode_is_valid(cls, value: Optional[str]) -> Optional[str]:
        return normalize_barcode(value)

    @field_validator("product_name")
    @classmethod
    def _product_name_requires_en(cls, value: Dict[str, str]) -> Dict[str, str]:
        if not (value.get("en") or "").strip():
            raise ValueError('product_name must include a non-empty "en" key.')
        return value


class ProductUpdateRequest(BaseModel):
    expected_version: Optional[int] = Field(default=None,ge=1)
    """PATCH /products/{product_id} - every field is optional; only the
    fields actually present in the request body are written (the handler
    uses model_dump(exclude_unset=True), not exclude_none=True - a field
    explicitly sent as null IS written as NULL, a field simply omitted is
    left untouched). `source` is deliberately not a field here at all."""
    product_name: Optional[Dict[str, str]] = None
    brand: Optional[Dict[str, str]] = None
    category: Optional[Dict[str, str]] = None
    description: Optional[Dict[str, str]] = None
    current_price: Optional[float] = Field(default=None, ge=0)
    cost_price: Optional[float] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, pattern=r"^[A-Z]{3}$")
    # Sent as null (or "") it clears the stored barcode; omitted leaves it alone.
    sku: Optional[str] = None

    @field_validator("sku")
    @classmethod
    def _sku_is_valid(cls, value):
        return normalize_sku(value)

    barcode: Optional[str] = None

    @field_validator("barcode")
    @classmethod
    def _barcode_is_valid(cls, value: Optional[str]) -> Optional[str]:
        return normalize_barcode(value)

    @field_validator("product_name")
    @classmethod
    def _product_name_requires_en_when_present(cls, value: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        if value is not None and not (value.get("en") or "").strip():
            raise ValueError('product_name must include a non-empty "en" key.')
        return value


class InventoryUpdateRequest(BaseModel):
    """PATCH /products/{product_id}/inventory - upserts the product's one
    inventory row. All three fields are optional; an omitted field is
    left as-is on an existing row, or takes inventory's own DB DEFAULT on
    first creation (stock_quantity=0, reorder_level=10, safety_stock=5)."""
    stock_quantity: Optional[Decimal] = Field(default=None, ge=0, le=1_000_000_000, max_digits=14, decimal_places=4)
    reorder_level: Optional[Decimal] = Field(default=None, ge=0, le=1_000_000_000, max_digits=14, decimal_places=4)
    safety_stock: Optional[Decimal] = Field(default=None, ge=0, le=1_000_000_000, max_digits=14, decimal_places=4)


# --- query functions --------------------------------------------------------

def list_products(conn, tenant_id: str, limit: int = DEFAULT_LIMIT, offset: int = 0, search: Optional[str] = None) -> dict:
    """
    Paginated list of the tenant's own real, active products, each with
    its resolved (single-language) name/brand/category, real price
    fields, and real current stock_quantity from a LEFT JOIN to
    `inventory` - NULL when no inventory row exists yet for that product
    (never fabricated as 0, which would look identical to "confirmed
    zero stock").

    search does a case-insensitive substring match against the product name
    in every language, the brand and the category (what the search box
    promises), with LIKE wildcards in the term escaped.
    """
    search = (search or "").strip() or None
    where_search = ""
    search_params: list = []
    if search:
        # Name in any language, brand or category - what the search box offers.
        where_search = f" AND ({text_search.product_match('p')} OR p.sku ILIKE %s)"
        like_pattern = text_search.like_pattern(search)
        search_params = [like_pattern, like_pattern, like_pattern,like_pattern]

    with conn.cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) FROM products p WHERE p.tenant_id = %s AND p.deleted_at IS NULL{where_search};",
            [tenant_id, *search_params],
        )
        total = cursor.fetchone()[0]

        cursor.execute(
            f"""
            SELECT p.product_id, {_NAME_EXPR} AS name, {_BRAND_EXPR} AS brand, {_CATEGORY_EXPR} AS category,
                   p.current_price, p.cost_price, p.currency, p.source, i.stock_quantity, p.sku,p.version
            FROM products p
            LEFT JOIN LATERAL (
                SELECT stock_quantity FROM inventory
                WHERE tenant_id = p.tenant_id AND product_id = p.product_id
                ORDER BY updated_at DESC NULLS LAST, inventory_id
                LIMIT 1
            ) i ON TRUE
            WHERE p.tenant_id = %s AND p.deleted_at IS NULL{where_search}
            ORDER BY name ASC
            LIMIT %s OFFSET %s;
            """,
            [tenant_id, *search_params, limit, offset],
        )
        rows = cursor.fetchall()

    products = [
        {
            "product_id": str(product_id),
            "product_name": name,
            "brand": brand,
            "category": category,
            "current_price": float(current_price),
            "cost_price": float(cost_price) if cost_price is not None else None,
            "currency": currency,
            "source": source,
            "stock_quantity": as_quantity(stock_quantity),
            "sku": sku,
            "version": version,
        }
        for product_id, name, brand, category, current_price, cost_price, currency, source, stock_quantity,sku,version in rows
    ]

    return {"products": products, "total": int(total), "limit": limit, "offset": offset}


def get_product(conn, tenant_id: str, product_id: str) -> Optional[dict]:
    """Single product, full detail shape - the complete JSONB for
    product_name/brand/category/description (every locale, not resolved
    to one), since a detail view is exactly what an edit form needs.
    Returns None (never raises) for a missing or soft-deleted product_id -
    the caller maps that to a 404."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT product_id, product_name, brand, category, description,
                   current_price, cost_price, currency, source, created_at, updated_at,
                   metadata->>'barcode', sku, version
            FROM products
            WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL;
            """,
            (tenant_id, product_id),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        (
            pid, product_name, brand, category, description,
            current_price, cost_price, currency, source, created_at, updated_at, barcode, sku, version,
        ) = row

        # No uniqueness constraint on (tenant_id, product_id) in `inventory` -
        # ORDER BY ... LIMIT 1 is a deliberate defensive read, not an
        # assumption a second row can never exist, even though every writer
        # in this router maintains at most one.
        cursor.execute(
            """
            SELECT stock_quantity, reorder_level, safety_stock, warehouse_location, updated_at
            FROM inventory
            WHERE tenant_id = %s AND product_id = %s
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 1;
            """,
            (tenant_id, product_id),
        )
        inv_row = cursor.fetchone()

    inventory = None
    if inv_row is not None:
        stock_quantity, reorder_level, safety_stock, warehouse_location, inv_updated_at = inv_row
        inventory = {
            "stock_quantity": as_quantity(stock_quantity),
            "reorder_level": as_quantity(reorder_level),
            "safety_stock": as_quantity(safety_stock),
            "warehouse_location": warehouse_location,
            "updated_at": inv_updated_at.isoformat() if inv_updated_at else None,
        }

    return {
        "product_id": str(pid),
        "product_name": product_name,
        "brand": brand,
        "category": category,
        "description": description,
        "current_price": float(current_price),
        "cost_price": float(cost_price) if cost_price is not None else None,
        "currency": currency,
        "source": source,
        "barcode": barcode,
        "sku": sku,
        "version": version,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "inventory": inventory,
    }


def create_product(
    conn, tenant_id: str, user_id: Optional[str],
    product_name: Dict[str, str], brand: Optional[Dict[str, str]], category: Optional[Dict[str, str]],
    description: Optional[Dict[str, str]], current_price: float, cost_price: Optional[float],
    currency: str, initial_stock_quantity: Optional[Decimal] = None, barcode: Optional[str] = None, sku: Optional[str] = None,
) -> dict:
    """Inserts a new MANUAL product, plus an inventory row only when
    initial_stock_quantity is given (None = stock not tracked). JSONB columns are
    inserted via json.dumps(...) + an explicit ::jsonb cast - psycopg2
    does not auto-adapt a Python dict to jsonb."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO products
                (tenant_id, product_name, brand, category, description, current_price,
                 cost_price, currency, source, metadata, created_by_user_id, updated_by_user_id, sku)
            VALUES (%s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, 'MANUAL', %s::jsonb, %s, %s, %s)
            RETURNING product_id;
            """,
            (
                tenant_id, json.dumps(product_name),
                json.dumps(brand) if brand is not None else None,
                json.dumps(category) if category is not None else None,
                json.dumps(description) if description is not None else None,
                current_price, cost_price, currency, json.dumps({"barcode": barcode} if barcode else {}), user_id, user_id, normalize_sku(sku),
            ),
        )
        product_id = str(cursor.fetchone()[0])

        if initial_stock_quantity is not None:
            cursor.execute(
                "INSERT INTO inventory (tenant_id, product_id, stock_quantity) VALUES (%s, %s, %s);",
                (tenant_id, product_id, initial_stock_quantity),
            )

    return get_product(conn, tenant_id, product_id)


def update_product(conn, tenant_id: str, user_id: Optional[str], product_id: str, fields: Dict[str, object]) -> Optional[dict]:
    """Partial update: only the keys present in `fields` are written. The
    SET clause is built only from _UPDATABLE_COLUMNS, a fixed, hardcoded
    whitelist of real column names - `fields` can never inject an
    arbitrary column into the SQL text. Returns None (never raises) if
    product_id doesn't resolve to an active product for this tenant, or
    is already soft-deleted."""
    unknown = set(fields) - _UPDATABLE_COLUMNS
    if unknown:
        raise ProductValidationError(f"Not updatable via this endpoint: {sorted(unknown)}")

    if not fields:
        return get_product(conn, tenant_id, product_id)

    set_clauses = []
    params: list = []
    for column in _UPDATABLE_COLUMNS:
        if column not in fields:
            continue
        if column == "barcode":
            # Lives in the metadata document; every other metadata key is left as-is.
            if fields[column]:
                set_clauses.append("metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('barcode', %s::text)")
                params.append(fields[column])
            else:
                set_clauses.append("metadata = COALESCE(metadata, '{}'::jsonb) - 'barcode'")
        elif column in _UPDATABLE_JSONB_COLUMNS:
            set_clauses.append(f"{column} = %s::jsonb")
            params.append(json.dumps(fields[column]) if fields[column] is not None else None)
        else:
            set_clauses.append(f"{column} = %s")
            params.append(fields[column])
    set_clauses.append("updated_by_user_id = %s")
    params.append(user_id)
    params.extend([tenant_id, product_id])

    with conn.cursor() as cursor:
        cursor.execute(
            f"UPDATE products SET {', '.join(set_clauses)} "
            "WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL "
            "RETURNING product_id;",
            params,
        )
        updated = cursor.fetchone()

    if updated is None:
        return None
    return get_product(conn, tenant_id, product_id)


def delete_product(conn, tenant_id: str, product_id: str) -> bool:
    """Soft-delete only (`deleted_at = NOW()`) - never a real DELETE FROM
    (ON DELETE RESTRICT from invoice_items, and destroying product_price_
    history's audit trail). Returns False if already soft-deleted."""
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE products SET deleted_at = NOW() "
            "WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL "
            "RETURNING product_id;",
            (tenant_id, product_id),
        )
        return cursor.fetchone() is not None


def upsert_inventory(
    conn, tenant_id: str, product_id: str,
    stock_quantity: Optional[Decimal] = None, reorder_level: Optional[Decimal] = None, safety_stock: Optional[Decimal] = None,
) -> Optional[dict]:
    """Creates the product's inventory row if none exists yet, otherwise
    updates only the fields provided. Returns None (never creates a row)
    if product_id doesn't resolve to an active product for this tenant -
    an inventory row for a nonexistent/deleted product would be silent
    orphan data."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM products WHERE tenant_id = %s AND product_id = %s AND deleted_at IS NULL FOR UPDATE;",
            (tenant_id, product_id),
        )
        if cursor.fetchone() is None:
            return None

        cursor.execute(
            "SELECT inventory_id FROM inventory WHERE tenant_id = %s AND product_id = %s "
            "ORDER BY updated_at DESC NULLS LAST, inventory_id LIMIT 1;",
            (tenant_id, product_id),
        )
        existing = cursor.fetchone()

        if existing is None:
            cursor.execute(
                """
                INSERT INTO inventory (tenant_id, product_id, stock_quantity, reorder_level, safety_stock)
                VALUES (%s, %s, COALESCE(%s, 0), COALESCE(%s, 10), COALESCE(%s, 5))
                RETURNING stock_quantity, reorder_level, safety_stock, warehouse_location, updated_at;
                """,
                (tenant_id, product_id, stock_quantity, reorder_level, safety_stock),
            )
        else:
            set_clauses = []
            params: list = []
            if stock_quantity is not None:
                set_clauses.append("stock_quantity = %s")
                params.append(stock_quantity)
            if reorder_level is not None:
                set_clauses.append("reorder_level = %s")
                params.append(reorder_level)
            if safety_stock is not None:
                set_clauses.append("safety_stock = %s")
                params.append(safety_stock)

            if set_clauses:
                params.append(existing[0])
                cursor.execute(
                    f"UPDATE inventory SET {', '.join(set_clauses)} WHERE inventory_id = %s "
                    "RETURNING stock_quantity, reorder_level, safety_stock, warehouse_location, updated_at;",
                    params,
                )
            else:
                cursor.execute(
                    "SELECT stock_quantity, reorder_level, safety_stock, warehouse_location, updated_at "
                    "FROM inventory WHERE inventory_id = %s;",
                    (existing[0],),
                )
        row = cursor.fetchone()

    stock, reorder, safety, warehouse_location, updated_at = row
    return {
        "stock_quantity": as_quantity(stock),
        "reorder_level": as_quantity(reorder),
        "safety_stock": as_quantity(safety),
        "warehouse_location": warehouse_location,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


# --- endpoints ---------------------------------------------------------------

@router.get("/products")
def list_products_endpoint(
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None, max_length=200),
    ctx: TenantContext = Depends(get_tenant_context),
) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = list_products(conn, ctx.tenant_id, limit=limit, offset=offset, search=search)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class ProductReferenceRequest(BaseModel):
    product_id: Optional[str] = None
    sku: Optional[str] = None
    product_name: Optional[str] = Field(default=None,max_length=255)
    barcode: Optional[str] = None

@router.post('/products/resolve-reference')
def resolve_product_reference(body: ProductReferenceRequest, ctx: TenantContext=Depends(get_tenant_context)):
    conn=db.app_role_connection(ctx.tenant_id,ctx.user_id)
    try:return resolve_reference(conn,ctx.tenant_id,body.model_dump(exclude_none=True))
    finally:conn.close()

@router.get("/products/{product_id}")
def get_product_endpoint(product_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        result = get_product(conn, ctx.tenant_id, product_id)
        conn.commit()
        if result is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return result
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/products")
def create_product_endpoint(body: ProductCreateRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_catalog_admin(conn, ctx.tenant_id, ctx.user_id)
        usage.ensure_capacity(conn, ctx.tenant_id, usage.TRACKED_PRODUCTS)
        result = create_product(
            conn, ctx.tenant_id, ctx.user_id, body.product_name, body.brand, body.category,
            body.description, body.current_price, body.cost_price, body.currency,
            body.initial_stock_quantity, body.barcode,
        )
        if body.sku:
            result = update_product(conn, ctx.tenant_id, ctx.user_id, result['product_id'], {'sku':body.sku})
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if getattr(exc,'pgcode',None)=='23505':raise HTTPException(409,'An active product already uses that SKU.') from None
        raise
    finally:
        conn.close()

    # Same real automatic-discovery trigger extraction.py's upload path
    # already fires for imported products (see that module's own
    # _publish_discovery_request() docstring) - without this, a tenant who
    # only ever adds products manually (the explicit no-POS/ERP segment)
    # would never get automatic competitor discovery at all, unlike a
    # tenant who imports a file. Fired after the connection above is
    # closed, same reasoning as extraction.py: a bare redis xadd, never a
    # Postgres call, needs no pooled connection held open for it.
    _publish_discovery_request(ctx.tenant_id)
    return result


@router.patch("/products/{product_id}")
def update_product_endpoint(product_id: str, body: ProductUpdateRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_catalog_admin(conn, ctx.tenant_id, ctx.user_id)
        values=body.model_dump(exclude_unset=True)
        expected=values.pop('expected_version',None)
        if expected is not None:
            with conn.cursor() as c:
                c.execute('SELECT version FROM products WHERE tenant_id=%s AND product_id=%s AND deleted_at IS NULL FOR UPDATE',(ctx.tenant_id,product_id))
                current=c.fetchone()
                if not current:raise HTTPException(404,'Product not found')
                if current[0]!=expected:raise HTTPException(409,'The product changed. Reload before saving.')
        result = update_product(conn, ctx.tenant_id, ctx.user_id, product_id, values)
        conn.commit()
        if result is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return result
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        if getattr(exc,'pgcode',None)=='23505':raise HTTPException(409,'An active product already uses that SKU.') from None
        raise
    finally:
        conn.close()


@router.delete("/products/{product_id}")
def delete_product_endpoint(product_id: str, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_catalog_admin(conn, ctx.tenant_id, ctx.user_id)
        deleted = delete_product(conn, ctx.tenant_id, product_id)
        conn.commit()
        if not deleted:
            raise HTTPException(status_code=404, detail="Product not found")
        return {"ok": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.patch("/products/{product_id}/inventory")
def update_product_inventory_endpoint(product_id: str, body: InventoryUpdateRequest, ctx: TenantContext = Depends(get_tenant_context)) -> dict:
    conn = db.app_role_connection(ctx.tenant_id, ctx.user_id)
    try:
        _require_catalog_admin(conn, ctx.tenant_id, ctx.user_id)
        result = upsert_inventory(conn, ctx.tenant_id, product_id, body.stock_quantity, body.reorder_level, body.safety_stock)
        conn.commit()
        if result is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return result
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
