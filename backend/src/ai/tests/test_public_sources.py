"""market_inputs/public_sources.py: what customers see about where
competitors come from - categories only, in the shape the Market Scan
screen reads (frontend MarketScan.jsx: provider.provider, provider.configured)."""
from src.ai.market_inputs import public_sources


def test_provider_status_is_per_category_and_never_names_a_vendor():
    status = public_sources.provider_status([
        {"provider": "openstreetmap", "configured": True},
        {"provider": "google_places", "configured": False},
        {"provider": "apify_google_maps", "configured": False},
        {"provider": "web_search", "configured": False},
    ])
    assert status == [{"provider": "map_listing", "configured": True}, {"provider": "web_search", "configured": False}]
    text = repr(status).lower()
    for vendor in ("openstreetmap", "google", "apify", "searxng", "brave", "tavily"):
        assert vendor not in text


def test_a_run_reports_categories_and_generic_errors():
    run = public_sources.public_run({"run_id": "r1", "status": "partial", "providers": {
        "openstreetmap": {"status": "ok", "found": 3},
        "google_places": {"status": "skipped", "reason": "not_configured"},
        "web_search": {"status": "failed", "reason": "HTTP 403 from api.vendor.example"},
    }})
    assert set(run["providers"]) == {"map_listing", "web_search"}
    assert "vendor.example" not in repr(run) and "google" not in repr(run).lower()
