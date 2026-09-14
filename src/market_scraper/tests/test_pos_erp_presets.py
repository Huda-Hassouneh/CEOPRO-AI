import pytest

from src.market_scraper.pos_erp_presets import (
    ALL_PRESETS,
    CONNECTION_MECHANISMS,
    JORDAN_PHARMACY_PRESETS,
    onboarding_connector_hint,
    resolve_preset,
)


def test_all_presets_have_a_valid_connection_mechanism():
    for slug, preset in ALL_PRESETS.items():
        assert preset["connection_mechanism"] in CONNECTION_MECHANISMS, slug


def test_all_presets_have_required_fields():
    required = {
        "display_name", "vendor_of", "category", "hq_country", "confirmed_countries",
        "connection_mechanism", "mechanism_note", "source_note", "verified_live",
    }
    for slug, preset in ALL_PRESETS.items():
        assert required.issubset(preset.keys()), slug


def test_resolve_preset_returns_none_for_unknown_vendor():
    assert resolve_preset("not-a-real-vendor") is None


def test_dawatech_and_smart_systems_are_confirmed_jordan_pharmacy_vendors():
    assert "Jordan" in JORDAN_PHARMACY_PRESETS["dawatech"]["confirmed_countries"]
    assert "Jordan" in JORDAN_PHARMACY_PRESETS["smart_systems"]["confirmed_countries"]


def test_juleb_jordan_presence_is_flagged_as_unconfirmed_not_asserted():
    juleb = JORDAN_PHARMACY_PRESETS["juleb"]
    assert "Jordan" not in juleb["confirmed_countries"]
    assert "discrepancy" in juleb["mechanism_note"].lower()


def test_onboarding_connector_hint_for_generic_api_vendor_points_at_api_endpoint():
    hint = onboarding_connector_hint("foodics")
    assert hint["endpoint"] == "POST /onboarding/connect/api"
    assert "field_mapping" in hint["required_from_tenant"]


def test_onboarding_connector_hint_for_vendor_direct_request_has_no_endpoint():
    hint = onboarding_connector_hint("dawatech")
    assert hint["endpoint"] is None


def test_onboarding_connector_hint_for_database_vendor_points_at_database_endpoint():
    hint = onboarding_connector_hint("tally")
    assert hint["endpoint"] == "POST /onboarding/connect/database"


def test_onboarding_connector_hint_raises_for_unknown_vendor():
    with pytest.raises(KeyError):
        onboarding_connector_hint("not-a-real-vendor")


def test_no_duplicate_slugs_across_preset_groups():
    # ALL_PRESETS merges three dicts - confirm no silent overwrite happened
    # by checking the combined size equals the sum of the three groups.
    from src.market_scraper.pos_erp_presets import JORDAN_GENERAL_PRESETS, MIDDLE_EAST_PRESETS
    total = len(JORDAN_PHARMACY_PRESETS) + len(JORDAN_GENERAL_PRESETS) + len(MIDDLE_EAST_PRESETS)
    assert len(ALL_PRESETS) == total
