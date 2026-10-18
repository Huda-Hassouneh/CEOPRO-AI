import pytest

from src.market_scraper.company_target_markets import (
    MARKET_TYPE_COUNTRY, MARKET_TYPE_GLOBAL, MARKET_TYPE_REGION,
    _normalize_target_markets, extract_country_codes, extract_region_names,
    get_tenant_target_markets, has_global_target_market, set_tenant_target_markets,
)

# --- _normalize_target_markets() - pure validation, no DB needed ----------


def test_normalizes_a_country_entry_uppercasing_the_code():
    assert _normalize_target_markets([{"market_type": "COUNTRY", "country_code": "ae"}]) == [
        {"market_type": "COUNTRY", "country_code": "AE", "region_name": None},
    ]


def test_rejects_a_non_two_letter_country_code():
    with pytest.raises(ValueError, match="invalid country code"):
        _normalize_target_markets([{"market_type": "COUNTRY", "country_code": "Jordan"}])


def test_rejects_a_country_entry_missing_a_code():
    with pytest.raises(ValueError, match="invalid country code"):
        _normalize_target_markets([{"market_type": "COUNTRY"}])


def test_rejects_a_country_entry_carrying_a_region_name():
    with pytest.raises(ValueError, match="must not carry a region_name"):
        _normalize_target_markets([{"market_type": "COUNTRY", "country_code": "AE", "region_name": "Gulf"}])


def test_normalizes_a_region_entry_collapsing_whitespace():
    assert _normalize_target_markets([{"market_type": "REGION", "region_name": "  Middle   East  "}]) == [
        {"market_type": "REGION", "country_code": None, "region_name": "Middle East"},
    ]


def test_rejects_an_empty_region_name():
    with pytest.raises(ValueError, match="region_name must not be empty"):
        _normalize_target_markets([{"market_type": "REGION", "region_name": "   "}])


def test_rejects_a_region_entry_carrying_a_country_code():
    with pytest.raises(ValueError, match="must not carry a country_code"):
        _normalize_target_markets([{"market_type": "REGION", "region_name": "Europe", "country_code": "FR"}])


def test_rejects_an_overlong_region_name():
    with pytest.raises(ValueError, match="at most 100 characters"):
        _normalize_target_markets([{"market_type": "REGION", "region_name": "x" * 101}])


def test_normalizes_a_global_entry():
    assert _normalize_target_markets([{"market_type": "GLOBAL"}]) == [
        {"market_type": "GLOBAL", "country_code": None, "region_name": None},
    ]


def test_rejects_a_global_entry_carrying_a_country_code():
    with pytest.raises(ValueError, match="must not carry a country_code or region_name"):
        _normalize_target_markets([{"market_type": "GLOBAL", "country_code": "AE"}])


def test_rejects_global_combined_with_a_country():
    with pytest.raises(ValueError, match="GLOBAL cannot be combined"):
        _normalize_target_markets([{"market_type": "GLOBAL"}, {"market_type": "COUNTRY", "country_code": "AE"}])


def test_rejects_global_combined_with_a_region():
    with pytest.raises(ValueError, match="GLOBAL cannot be combined"):
        _normalize_target_markets([{"market_type": "REGION", "region_name": "Europe"}, {"market_type": "GLOBAL"}])


def test_rejects_an_unknown_market_type():
    with pytest.raises(ValueError, match="invalid market_type"):
        _normalize_target_markets([{"market_type": "CONTINENT", "region_name": "Africa"}])


def test_deduplicates_countries_case_insensitively_keeping_first_occurrence():
    assert _normalize_target_markets([
        {"market_type": "COUNTRY", "country_code": "ae"},
        {"market_type": "COUNTRY", "country_code": "AE"},
    ]) == [{"market_type": "COUNTRY", "country_code": "AE", "region_name": None}]


def test_deduplicates_regions_case_insensitively_keeping_first_occurrence():
    assert _normalize_target_markets([
        {"market_type": "REGION", "region_name": "europe"},
        {"market_type": "REGION", "region_name": "Europe"},
    ]) == [{"market_type": "REGION", "country_code": None, "region_name": "europe"}]


def test_empty_list_normalizes_to_empty():
    assert _normalize_target_markets([]) == []


def test_country_and_region_can_coexist_without_global():
    result = _normalize_target_markets([
        {"market_type": "COUNTRY", "country_code": "AE"},
        {"market_type": "REGION", "region_name": "Europe"},
    ])
    assert result == [
        {"market_type": "COUNTRY", "country_code": "AE", "region_name": None},
        {"market_type": "REGION", "country_code": None, "region_name": "Europe"},
    ]


# --- extract_country_codes() / extract_region_names() / has_global_target_market() ---

_MIXED = [
    {"market_type": "COUNTRY", "country_code": "AE", "region_name": None},
    {"market_type": "COUNTRY", "country_code": "SA", "region_name": None},
    {"market_type": "REGION", "country_code": None, "region_name": "Europe"},
]


def test_extract_country_codes_returns_only_country_type_entries():
    assert extract_country_codes(_MIXED) == ["AE", "SA"]


def test_extract_region_names_returns_only_region_type_entries():
    assert extract_region_names(_MIXED) == ["Europe"]


def test_has_global_target_market_is_false_without_a_global_entry():
    assert has_global_target_market(_MIXED) is False


def test_has_global_target_market_is_true_with_a_global_entry():
    assert has_global_target_market([{"market_type": "GLOBAL", "country_code": None, "region_name": None}]) is True


def test_extractors_return_empty_for_an_empty_list():
    assert extract_country_codes([]) == []
    assert extract_region_names([]) == []
    assert has_global_target_market([]) is False


# --- set_tenant_target_markets()/get_tenant_target_markets() - fake conn/cursor ---


class _FakeCursor:
    def __init__(self, tenant_exists=True):
        self.tenant_exists = tenant_exists
        self.executed = []
        self.executemany_args = None

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def executemany(self, query, seq_of_params):
        self.executemany_args = list(seq_of_params)

    def fetchone(self):
        return (1,) if self.tenant_exists else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, tenant_exists=True):
        self.cursor_obj = _FakeCursor(tenant_exists)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


def test_set_target_markets_raises_for_an_unknown_tenant():
    conn = _FakeConn(tenant_exists=False)
    with pytest.raises(ValueError, match="tenant_id not found"):
        set_tenant_target_markets(conn, "missing-tenant", [{"market_type": "COUNTRY", "country_code": "JO"}])
    assert conn.committed is False


def test_set_target_markets_inserts_each_normalized_entry():
    conn = _FakeConn(tenant_exists=True)
    result = set_tenant_target_markets(conn, "tenant-1", [
        {"market_type": "COUNTRY", "country_code": "ae"},
        {"market_type": "REGION", "region_name": "Europe"},
    ])
    assert result == [
        {"market_type": "COUNTRY", "country_code": "AE", "region_name": None},
        {"market_type": "REGION", "country_code": None, "region_name": "Europe"},
    ]
    assert conn.cursor_obj.executemany_args == [
        ("tenant-1", "COUNTRY", "AE", None),
        ("tenant-1", "REGION", None, "Europe"),
    ]
    assert conn.committed is True


def test_set_target_markets_with_an_empty_list_clears_without_inserting():
    conn = _FakeConn(tenant_exists=True)
    result = set_tenant_target_markets(conn, "tenant-1", [])
    assert result == []
    assert conn.cursor_obj.executemany_args is None
    assert conn.committed is True
    delete_calls = [q for q, _ in conn.cursor_obj.executed if "DELETE FROM company_target_markets" in q]
    assert len(delete_calls) == 1


class _FakeReadCursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, params=None):
        pass

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeReadConn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _FakeReadCursor(self.rows)


def test_get_target_markets_returns_the_real_stored_entries():
    conn = _FakeReadConn([("COUNTRY", "AE", None), ("REGION", None, "Europe")])
    assert get_tenant_target_markets(conn, "tenant-1") == [
        {"market_type": "COUNTRY", "country_code": "AE", "region_name": None},
        {"market_type": "REGION", "country_code": None, "region_name": "Europe"},
    ]


def test_get_target_markets_is_an_empty_list_when_nothing_declared():
    conn = _FakeReadConn([])
    assert get_tenant_target_markets(conn, "tenant-1") == []
