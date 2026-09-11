import pytest

from src.market_scraper.company_geo_profile import _normalize_country_codes, set_tenant_search_scope


def test_normalize_uppercases_codes():
    assert _normalize_country_codes(["jo", "ae"]) == ["JO", "AE"]


def test_normalize_deduplicates_preserving_first_occurrence_order():
    assert _normalize_country_codes(["JO", "AE", "jo"]) == ["JO", "AE"]


def test_normalize_rejects_a_non_two_letter_code():
    with pytest.raises(ValueError, match="invalid country code"):
        _normalize_country_codes(["Jordan"])


def test_normalize_rejects_a_non_alphabetic_code():
    with pytest.raises(ValueError, match="invalid country code"):
        _normalize_country_codes(["J0"])


def test_normalize_of_empty_list_is_empty():
    assert _normalize_country_codes([]) == []


# These validation branches all raise before set_tenant_search_scope() ever
# touches `conn`, so they're safe to exercise with conn=None - no database
# needed, and it keeps the "never let a user type a kilometer number"
# contract covered by the always-on offline suite, not just the skipped
# live-DB tests.

def test_rejects_an_unknown_scope_level():
    with pytest.raises(ValueError, match="invalid search_scope_level"):
        set_tenant_search_scope(None, "tenant-1", search_scope_level="GALAXY")


def test_custom_scope_without_a_radius_is_rejected():
    with pytest.raises(ValueError, match="custom_radius_km is required"):
        set_tenant_search_scope(None, "tenant-1", search_scope_level="CUSTOM")


def test_custom_radius_without_custom_scope_is_rejected():
    with pytest.raises(ValueError, match="only accepted together"):
        set_tenant_search_scope(None, "tenant-1", search_scope_level="PROVINCE", custom_radius_km=40)


def test_non_positive_custom_radius_is_rejected():
    with pytest.raises(ValueError, match="must be positive"):
        set_tenant_search_scope(None, "tenant-1", search_scope_level="CUSTOM", custom_radius_km=0)
