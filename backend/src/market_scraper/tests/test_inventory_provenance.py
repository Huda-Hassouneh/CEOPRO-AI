from __future__ import annotations

from decimal import Decimal

import pytest

from src.market_scraper.inventory_provenance import (
    InventoryProvenanceError,
    _decimal,
    _read_limit,
    _revision,
    persist_woocommerce_inventory_records,
)
from src.market_scraper.woocommerce import WooRecord


def test_inventory_decimal_preserves_precision_and_negative_provider_values():
    assert _decimal("1.2500") == Decimal("1.2500")
    assert _decimal(-2) == Decimal("-2")
    for value in (True, None, float("nan"), float("inf"), "not-a-number"):
        with pytest.raises(InventoryProvenanceError):
            _decimal(value)


def test_provider_revision_and_history_limit_validation_fail_closed():
    assert _revision("2026-10-20T12:00:00Z") == "2026-10-20T12:00:00Z"
    for value in ("", "x" * 256, 42):
        with pytest.raises(InventoryProvenanceError):
            _revision(value)
    for limit in (True, 0, 501, 1.5):
        with pytest.raises(InventoryProvenanceError):
            _read_limit(limit)


def test_woocommerce_does_not_invent_stock_or_location_when_stock_is_unmanaged():
    class UnusedConnection:
        def cursor(self):
            raise AssertionError("unmanaged quantity must not reach persistence")

    records = [
        WooRecord("product", 1, {"id": 1, "manage_stock": False, "stock_quantity": 99}),
        WooRecord("variation", 2, {"id": 2, "manage_stock": "parent", "stock_quantity": None}, 1),
    ]
    assert persist_woocommerce_inventory_records(UnusedConnection(), "source", records) == []


def test_woocommerce_rejects_nonfinite_provider_quantity_before_database_write():
    class UnusedConnection:
        def cursor(self):
            raise AssertionError("invalid quantity must not reach persistence")

    record = WooRecord("product", 1, {"id": 1, "manage_stock": True, "stock_quantity": float("nan")})
    with pytest.raises(InventoryProvenanceError):
        persist_woocommerce_inventory_records(UnusedConnection(), "source", [record])
