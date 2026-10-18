"""Offline tests for price_coverage.py: reason classification, summary over all
products, paging, and that covered products are hidden unless asked for."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from src.market_scraper import price_coverage as pc

NOW = datetime.now(timezone.utc)


def _conn(rows):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = rows
    return conn


def _row(pid, name, mappings=0, prices=0, allowed=0, restricted=None, last=None, reference=0, lookup=None, barcode=False,
         foreign=0, foreign_reference=0, last_reference=None, inactive=0):
    return (pid, name, 10, "JOD", mappings, prices, allowed, restricted or [], last, reference, lookup, NOW if lookup else None,
            barcode, foreign, foreign_reference, last_reference, inactive)


ROWS = [
    _row("p1", "Covered", mappings=1, prices=2, allowed=1, last=NOW),
    _row("p2", "Nobody sells it"),
    _row("p3", "Awaiting review", mappings=1, restricted=["s2", "s1"]),
    _row("p4", "Forbidden", mappings=1),
    _row("p5", "Approved but empty", mappings=1, allowed=1),
]


def test_summary_counts_every_product_and_every_reason():
    result = pc.get_price_coverage(_conn(ROWS), "t1")
    assert result["summary"] == {
        "total_products": 5, "with_market_price": 1, "without_market_price": 4,
        "with_competitor_price": 1, "with_reference_price_only": 0, "coverage_pct": 20.0,
        "products_without_barcode": 5, "gaps_without_barcode": 4,
        "gaps_by_reason": {pc.REASON_NO_MAPPING: 1, pc.REASON_TERMS: 1, pc.REASON_ROBOTS: 1, pc.REASON_NO_DATA: 1},
        "stale_prices": 0, "currency_mismatches": 0, "inactive_mappings": 0, "needs_attention": 4,
        "stale_after_days": pc.STALE_AFTER_DAYS,
    }


def test_gaps_carry_their_reason_and_the_sources_to_review():
    items = {i["product_id"]: i for i in pc.get_price_coverage(_conn(ROWS), "t1")["products"]}
    assert set(items) == {"p2", "p3", "p4", "p5"}  # the covered product is not listed
    assert items["p2"]["reason_code"] == pc.REASON_NO_MAPPING and items["p2"]["action"] is None
    assert items["p3"]["reason_code"] == pc.REASON_TERMS
    assert items["p3"]["action"] == "review_source" and items["p3"]["source_ids"] == ["s1", "s2"]
    assert items["p4"]["reason_code"] == pc.REASON_ROBOTS
    assert items["p5"]["reason_code"] == pc.REASON_NO_DATA


def test_covered_products_are_listed_on_request_with_their_latest_price_time():
    items = pc.get_price_coverage(_conn(ROWS), "t1", include_covered=True)["products"]
    covered = next(i for i in items if i["product_id"] == "p1")
    assert covered["has_market_price"] is True and covered["reason_code"] is None
    assert covered["competitor_prices"] == 2 and covered["last_price_at"] == NOW.isoformat()


def test_paging_applies_to_the_list_but_never_to_the_summary():
    result = pc.get_price_coverage(_conn(ROWS), "t1", limit=2, offset=1)
    assert [i["product_id"] for i in result["products"]] == ["p3", "p4"]
    assert result["summary"]["total_products"] == 5


def test_a_tenant_with_no_products_has_no_percentage_rather_than_a_misleading_100():
    result = pc.get_price_coverage(_conn([]), "t1")
    assert result["summary"]["coverage_pct"] is None and result["products"] == []


def test_a_market_reference_price_counts_as_covered_and_says_so():
    rows = [_row("p1", "Competitor", mappings=1, prices=1), _row("p2", "Reference only", reference=2, lookup="FOUND")]
    result = pc.get_price_coverage(_conn(rows), "t1", include_covered=True)
    assert result["summary"]["with_market_price"] == 2
    assert result["summary"]["with_competitor_price"] == 1 and result["summary"]["with_reference_price_only"] == 1
    by_id = {i["product_id"]: i for i in result["products"]}
    assert by_id["p1"]["price_basis"] == "competitor" and by_id["p2"]["price_basis"] == "market_reference"
    assert by_id["p2"]["reason_code"] is None and by_id["p2"]["reference_prices"] == 2


def test_a_gap_shows_what_the_open_market_lookup_already_tried():
    rows = [_row("p1", "Searched, nothing", lookup="NOTHING_FOUND"), _row("p2", "Never searched")]
    items = {i["product_id"]: i for i in pc.get_price_coverage(_conn(rows), "t1")["products"]}
    assert items["p1"]["market_lookup"] == {"outcome": "NOTHING_FOUND", "last_attempt_at": NOW.isoformat()}
    assert items["p2"]["market_lookup"] is None


def test_gaps_without_a_barcode_suggest_adding_one_and_the_summary_counts_them():
    rows = [_row("p1", "Gap, no code"), _row("p2", "Gap, has code", barcode=True), _row("p3", "Covered, no code", prices=1, mappings=1)]
    result = pc.get_price_coverage(_conn(rows), "t1")
    items = {i["product_id"]: i for i in result["products"]}
    assert items["p1"]["suggestion"] == "add_barcode" and items["p1"]["has_barcode"] is False
    assert items["p2"]["suggestion"] is None and items["p2"]["has_barcode"] is True
    assert "p3" not in items
    assert result["summary"]["products_without_barcode"] == 2 and result["summary"]["gaps_without_barcode"] == 1


def test_the_missing_barcode_worklist_lists_every_product_without_one_price_gaps_first():
    rows = [_row("p1", "A covered", prices=1, mappings=1), _row("p2", "B gap"), _row("p3", "C has code", barcode=True), _row("p4", "D covered by reference", reference=1)]
    result = pc.get_price_coverage(_conn(rows), "t1", missing_barcode=True)
    assert [i["product_id"] for i in result["products"]] == ["p2", "p1", "p4"]
    assert result["summary"]["total_products"] == 4  # the summary still covers everything


def test_barcode_summary_counts_products_with_a_barcode():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (8, 2)
    assert pc.get_barcode_summary(conn, "t1") == {"products": 8, "with_barcode": 2, "coverage_pct": 25.0}
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (0, 0)
    assert pc.get_barcode_summary(conn, "t1")["coverage_pct"] is None


def test_each_gap_carries_the_next_step_that_resolves_it():
    items = {i["product_id"]: i for i in pc.get_price_coverage(_conn(ROWS), "t1")["products"]}
    assert items["p2"]["next_action"] == "add_barcode"  # nobody matched and no barcode
    assert items["p3"]["next_action"] == "review_source"
    assert items["p4"]["next_action"] == "enter_price"
    assert items["p5"]["next_action"] == "check_collection"
    with_barcode = pc.get_price_coverage(_conn([_row("p9", "Has barcode", barcode=True)]), "t1")["products"][0]
    assert with_barcode["next_action"] == "add_competitor"


def test_an_old_price_is_covered_but_stale_and_listed_for_refresh():
    old = NOW - timedelta(days=pc.STALE_AFTER_DAYS + 5)
    rows = [_row("p1", "Old price", mappings=1, prices=1, allowed=1, last=old), _row("p2", "Fresh", mappings=1, prices=1, allowed=1, last=NOW)]
    result = pc.get_price_coverage(_conn(rows), "t1", now=NOW)
    assert result["summary"]["with_market_price"] == 2 and result["summary"]["stale_prices"] == 1
    assert [i["product_id"] for i in result["products"]] == ["p1"]  # fresh and fine: not listed
    item = result["products"][0]
    assert item["has_market_price"] is True and item["issues"] == [pc.ISSUE_STALE]
    assert item["price_age_days"] == pc.STALE_AFTER_DAYS + 5 and item["next_action"] == "refresh_prices"


def test_the_newest_of_competitor_and_reference_prices_decides_staleness():
    old = NOW - timedelta(days=pc.STALE_AFTER_DAYS + 40)
    row = _row("p1", "Recent reference", mappings=1, prices=1, allowed=1, last=old, reference=1, last_reference=NOW)
    item = pc.get_price_coverage(_conn([row]), "t1", include_covered=True, now=NOW)["products"][0]
    assert item["issues"] == [] and item["price_age_days"] == 0


def test_prices_in_another_currency_are_flagged_not_hidden():
    rows = [_row("p1", "Priced in USD", mappings=1, prices=2, allowed=1, last=NOW, foreign=2)]
    result = pc.get_price_coverage(_conn(rows), "t1", now=NOW)
    assert result["summary"]["currency_mismatches"] == 1 and result["summary"]["with_market_price"] == 1
    item = result["products"][0]
    assert item["issues"] == [pc.ISSUE_CURRENCY] and item["foreign_currency_prices"] == 2
    assert item["next_action"] == "check_currency"


def test_a_switched_off_competitor_mapping_is_reported_with_the_gap():
    rows = [_row("p1", "Mapping off", inactive=1, barcode=True)]
    result = pc.get_price_coverage(_conn(rows), "t1", now=NOW)
    item = result["products"][0]
    assert result["summary"]["inactive_mappings"] == 1 and result["summary"]["needs_attention"] == 1
    assert item["reason_code"] == pc.REASON_NO_MAPPING and item["inactive_mappings"] == 1
    assert item["next_action"] == "review_mappings"
