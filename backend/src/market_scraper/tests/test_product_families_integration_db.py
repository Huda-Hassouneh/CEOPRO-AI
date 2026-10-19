"""
Integration test for product_families.py::select_family_representatives
against a real PostgreSQL instance (needs real transactions rows).
Skipped unless AI_TEST_DATABASE_URL is set, same convention as every
other *_integration_db.py test in this package.
"""
import json
import os
import uuid

import psycopg2
import pytest

from src.market_scraper.product_families import find_cost_sharing_family_size, select_family_representatives

DATABASE_URL = os.getenv("AI_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AI_TEST_DATABASE_URL not set - skipping live-DB integration test")


@pytest.fixture
def conn():
    connection = psycopg2.connect(DATABASE_URL)
    connection.autocommit = False
    yield connection
    connection.rollback()
    connection.close()


def _insert_company(conn) -> str:
    tenant_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO companies (tenant_id, business_name, country_code, primary_currency) "
            "VALUES (%s, %s, 'JO', 'JOD');",
            (tenant_id, f"Test Co {tenant_id[:8]}"),
        )
    return tenant_id


def _insert_product(conn, tenant_id: str, name: str, price: float = 0.30, currency: str = "JOD") -> str:
    """Defaults to a collapse-eligible price (below the 0.70 JOD
    threshold) so existing family-grouping tests keep testing what they
    say they test without every call site needing to know about the
    price gate; tests of the gate itself pass an explicit price."""
    product_id = str(uuid.uuid4())
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (product_id, tenant_id, product_name, current_price, currency) "
            "VALUES (%s, %s, %s, %s, %s);",
            (product_id, tenant_id, json.dumps({"en": name}), price, currency),
        )
    return product_id


def _insert_transaction(conn, tenant_id: str, product_id: str, quantity: int):
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO transactions "
            "(tenant_id, product_id, quantity_sold, unit_price, total_price, original_currency, transaction_date) "
            "VALUES (%s, %s, %s, 10.0, %s, 'JOD', NOW());",
            (tenant_id, product_id, quantity, 10.0 * quantity),
        )


def test_highest_selling_family_member_is_the_representative(conn):
    tenant_id = _insert_company(conn)
    low = _insert_product(conn, tenant_id, "1k Ohm Resistor")
    high = _insert_product(conn, tenant_id, "2k Ohm Resistor")
    _insert_transaction(conn, tenant_id, low, 5)
    _insert_transaction(conn, tenant_id, high, 500)

    products = [
        {"product_id": low, "product_name": "1k Ohm Resistor"},
        {"product_id": high, "product_name": "2k Ohm Resistor"},
    ]
    representatives = select_family_representatives(conn, tenant_id, products)

    assert len(representatives) == 1
    assert representatives[0]["product_id"] == high
    assert {m["product_id"] for m in representatives[0]["family_members"]} == {low, high}


def test_family_with_no_sales_data_falls_back_to_alphabetical(conn):
    tenant_id = _insert_company(conn)
    ten = _insert_product(conn, tenant_id, "Trail Shoe Size 10")
    nine = _insert_product(conn, tenant_id, "Trail Shoe Size 9")

    products = [
        {"product_id": ten, "product_name": "Trail Shoe Size 10"},
        {"product_id": nine, "product_name": "Trail Shoe Size 9"},
    ]
    representatives = select_family_representatives(conn, tenant_id, products)

    assert len(representatives) == 1  # same family - only the size number differs
    # No sales data for either - falls back to sorting by product_name as a
    # plain string (deterministic, not volume-based): "...10" < "...9" lexicographically.
    assert representatives[0]["product_id"] == ten


def test_genuinely_different_products_produce_separate_families(conn):
    tenant_id = _insert_company(conn)
    resistor = _insert_product(conn, tenant_id, "1k Ohm Resistor")
    pi = _insert_product(conn, tenant_id, "Raspberry Pi 4")

    products = [
        {"product_id": resistor, "product_name": "1k Ohm Resistor"},
        {"product_id": pi, "product_name": "Raspberry Pi 4"},
    ]
    representatives = select_family_representatives(conn, tenant_id, products)

    assert len(representatives) == 2


def test_products_at_or_above_the_price_threshold_are_never_collapsed(conn):
    """The actual precision guarantee, proven rather than asserted: two
    same-family_key products priced at 10 JOD (well above the 0.70
    threshold) must come back as two separate single-member families,
    even though a plain family_key() match would group them."""
    tenant_id = _insert_company(conn)
    low = _insert_product(conn, tenant_id, "1k Ohm Resistor", price=10.0)
    high = _insert_product(conn, tenant_id, "2k Ohm Resistor", price=10.0)

    products = [
        {"product_id": low, "product_name": "1k Ohm Resistor"},
        {"product_id": high, "product_name": "2k Ohm Resistor"},
    ]
    representatives = select_family_representatives(conn, tenant_id, products)

    assert len(representatives) == 2
    for rep in representatives:
        assert len(rep["family_members"]) == 1


def test_a_mixed_batch_only_collapses_the_eligible_side(conn):
    """Same family_key on both sides, but only the cheap pair is below
    threshold - the expensive one must stand alone while the cheap pair
    still collapses together."""
    tenant_id = _insert_company(conn)
    cheap_a = _insert_product(conn, tenant_id, "1k Ohm Resistor", price=0.10)
    cheap_b = _insert_product(conn, tenant_id, "2k Ohm Resistor", price=0.10)
    pricey = _insert_product(conn, tenant_id, "10k Ohm Resistor", price=10.0)

    products = [
        {"product_id": cheap_a, "product_name": "1k Ohm Resistor"},
        {"product_id": cheap_b, "product_name": "2k Ohm Resistor"},
        {"product_id": pricey, "product_name": "10k Ohm Resistor"},
    ]
    representatives = select_family_representatives(conn, tenant_id, products)

    by_size = {len(rep["family_members"]): rep for rep in representatives}
    assert set(by_size.keys()) == {1, 2}
    assert by_size[1]["product_id"] == pricey
    assert {m["product_id"] for m in by_size[2]["family_members"]} == {cheap_a, cheap_b}


def test_unknown_currency_is_never_collapsed_even_at_a_low_price(conn):
    """Precision over cost-saving: a currency the threshold map doesn't
    recognize is never treated as cheap, no matter how low the raw
    number is - avoids a fake, unconverted-FX precision claim."""
    tenant_id = _insert_company(conn)
    a = _insert_product(conn, tenant_id, "1k Ohm Resistor", price=0.01, currency="EGP")
    b = _insert_product(conn, tenant_id, "2k Ohm Resistor", price=0.01, currency="EGP")

    products = [
        {"product_id": a, "product_name": "1k Ohm Resistor"},
        {"product_id": b, "product_name": "2k Ohm Resistor"},
    ]
    representatives = select_family_representatives(conn, tenant_id, products)

    assert len(representatives) == 2


# ---------------------------------------------------------------------------
# find_cost_sharing_family_size() - the cost-margin gate's real family-size
# lookup (cost_ledger.py's family_size parameter, wired in by enqueue.py)
# ---------------------------------------------------------------------------

def test_family_size_is_one_with_no_siblings_at_all(conn):
    tenant_id = _insert_company(conn)
    solo = _insert_product(conn, tenant_id, "1k Ohm Resistor")  # default: 0.30 JOD, eligible
    conn.commit()

    assert find_cost_sharing_family_size(conn, tenant_id, solo) == 1


def test_family_size_counts_a_real_eligible_sibling(conn):
    tenant_id = _insert_company(conn)
    a = _insert_product(conn, tenant_id, "1k Ohm Resistor")
    b = _insert_product(conn, tenant_id, "2k Ohm Resistor")
    conn.commit()

    assert find_cost_sharing_family_size(conn, tenant_id, a) == 2
    assert find_cost_sharing_family_size(conn, tenant_id, b) == 2


def test_family_size_counts_several_real_eligible_siblings(conn):
    tenant_id = _insert_company(conn)
    a = _insert_product(conn, tenant_id, "1k Ohm Resistor")
    b = _insert_product(conn, tenant_id, "2k Ohm Resistor")
    c = _insert_product(conn, tenant_id, "3k Ohm Resistor")
    conn.commit()

    assert find_cost_sharing_family_size(conn, tenant_id, a) == 3


def test_family_size_is_one_when_the_product_itself_is_not_collapse_eligible(conn):
    """A product priced at/above the collapse threshold never shares cost
    through this path, regardless of what siblings exist - matches
    select_family_representatives()'s own precision-first gate."""
    tenant_id = _insert_company(conn)
    pricey = _insert_product(conn, tenant_id, "1k Ohm Resistor", price=10.0)
    _insert_product(conn, tenant_id, "2k Ohm Resistor", price=0.10)
    conn.commit()

    assert find_cost_sharing_family_size(conn, tenant_id, pricey) == 1


def test_family_size_excludes_a_sibling_that_is_not_itself_eligible(conn):
    """The product being evaluated is eligible, but its only same-family
    sibling is priced too high to share cost with - no real family exists
    to amortize against, so the size stays 1."""
    tenant_id = _insert_company(conn)
    cheap = _insert_product(conn, tenant_id, "1k Ohm Resistor", price=0.10)
    _insert_product(conn, tenant_id, "2k Ohm Resistor", price=10.0)
    conn.commit()

    assert find_cost_sharing_family_size(conn, tenant_id, cheap) == 1


def test_family_size_ignores_a_genuinely_different_product(conn):
    tenant_id = _insert_company(conn)
    resistor = _insert_product(conn, tenant_id, "1k Ohm Resistor")
    _insert_product(conn, tenant_id, "Raspberry Pi 4")
    conn.commit()

    assert find_cost_sharing_family_size(conn, tenant_id, resistor) == 1


def test_family_size_is_one_for_an_unknown_product(conn):
    tenant_id = _insert_company(conn)
    conn.commit()

    assert find_cost_sharing_family_size(conn, tenant_id, str(uuid.uuid4())) == 1
