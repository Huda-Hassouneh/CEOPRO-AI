"""Offline unit tests for classify_competitor_scope() - pure function, no
database needed. Live-DB confirmation-logic tests (the discovery_method-
aware branch inside classify_competitor() itself) live in
test_pricing_competitor_classification_integration_db.py and
test_domain_level_discovery_integration_db.py."""
from src.ai.pricing.competitor_classification import (
    SCOPE_BROAD_DOMAIN, SCOPE_NICHE_ITEM, SCOPE_PARTIAL_OVERLAP, classify_competitor_scope,
)


def test_single_matched_product_is_niche_item():
    assert classify_competitor_scope(1, 0.1) == SCOPE_NICHE_ITEM


def test_zero_matched_products_is_niche_item_by_default():
    assert classify_competitor_scope(0, 0.0) == SCOPE_NICHE_ITEM


def test_high_overlap_is_broad_domain():
    assert classify_competitor_scope(5, 0.7) == SCOPE_BROAD_DOMAIN


def test_middle_overlap_is_partial():
    assert classify_competitor_scope(3, 0.3) == SCOPE_PARTIAL_OVERLAP


def test_custom_broad_domain_threshold_is_honored():
    assert classify_competitor_scope(3, 0.2, broad_domain_threshold=0.15) == SCOPE_BROAD_DOMAIN


def test_zero_matched_products_from_a_domain_level_source_is_broad_domain_not_niche():
    # The one deliberate exception: a domain-level find with no product
    # mappings yet was found BY being a same-industry business, not by
    # carrying one specific SKU - "niche" would be backwards here.
    assert classify_competitor_scope(0, 0.0, discovery_method="PLACES_NEARBY") == SCOPE_BROAD_DOMAIN
    assert classify_competitor_scope(0, 0.0, discovery_method="INDUSTRY_KEYWORD_SEARCH") == SCOPE_BROAD_DOMAIN


def test_zero_matched_products_from_product_search_is_still_niche_item():
    assert classify_competitor_scope(0, 0.0, discovery_method="PRODUCT_SEARCH") == SCOPE_NICHE_ITEM
    assert classify_competitor_scope(0, 0.0, discovery_method=None) == SCOPE_NICHE_ITEM


def test_domain_level_exception_does_not_apply_once_a_real_product_is_mapped():
    # Once matched_product_count > 0, the ordinary rules take back over
    # even for a domain-sourced competitor.
    assert classify_competitor_scope(1, 0.5, discovery_method="PLACES_NEARBY") == SCOPE_NICHE_ITEM
