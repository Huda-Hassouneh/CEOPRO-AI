from src.market_scraper.policy import (
    CollectionMethod,
    SourceCapabilities,
    SourceStatus,
    evaluate_source,
    is_public_http_url,
)


def test_policy_prefers_official_api_over_scraping():
    decision = evaluate_source(SourceCapabilities(
        source_url="https://competitor.example/products",
        official_api_url="https://api.competitor.example/v1/products",
        public_web_collection_possible=True,
        terms_permit_collection=True,
        technical_controls_permit_collection=True,
    ))
    assert decision.status is SourceStatus.ALLOWED
    assert decision.method is CollectionMethod.OFFICIAL_API


def test_scraping_requires_terms_and_technical_review():
    capabilities = SourceCapabilities(
        source_url="https://competitor.example/products",
        public_web_collection_possible=True,
        terms_permit_collection=True,
    )
    decision = evaluate_source(capabilities)
    assert decision.status is SourceStatus.RESTRICTED
    assert decision.method is None


def test_forbidden_terms_and_private_urls_are_blocked():
    forbidden = evaluate_source(SourceCapabilities(
        source_url="https://competitor.example",
        terms_permit_collection=False,
    ))
    private = evaluate_source(SourceCapabilities(
        source_url="http://127.0.0.1/admin",
        terms_permit_collection=True,
    ))
    assert forbidden.status is SourceStatus.BLOCKED
    assert private.status is SourceStatus.BLOCKED


def test_public_url_validation_rejects_credentials_and_local_hosts():
    assert is_public_http_url("https://books.toscrape.com/")
    assert not is_public_http_url("file:///etc/passwd")
    assert not is_public_http_url("https://user:pass@example.com/")
    assert not is_public_http_url("http://localhost:8000/")
