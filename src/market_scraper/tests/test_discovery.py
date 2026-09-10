from src.market_scraper.discovery import CandidateSource, compute_website_identity_key, looks_like_manufacturer_or_wholesale


def test_flags_a_candidate_whose_domain_matches_the_brand():
    candidate = CandidateSource(product_name="Arduino Nano", url="https://arduino.cc/store/nano", title="Buy Nano")
    assert looks_like_manufacturer_or_wholesale(candidate, brand_tokens={"arduino"}) is True


def test_does_not_flag_a_third_party_retailer():
    candidate = CandidateSource(product_name="Arduino Nano", url="https://sparkfun.com/products/nano", title="Arduino Nano - SparkFun")
    assert looks_like_manufacturer_or_wholesale(candidate, brand_tokens={"arduino"}) is False


def test_flags_a_wholesale_signal_word_in_the_title():
    candidate = CandidateSource(product_name="Widget", url="https://example.com/item", title="Widget - Wholesale Distributor Pricing")
    assert looks_like_manufacturer_or_wholesale(candidate, brand_tokens=set()) is True


def test_identity_key_is_the_bare_hostname_for_an_ordinary_seller():
    assert compute_website_identity_key("https://www.sparkfun.com/products/nano") == "sparkfun.com"


def test_identity_key_strips_www_but_not_other_subdomains():
    assert compute_website_identity_key("https://shop.example.com/item") == "shop.example.com"


def test_two_different_paths_on_the_same_ordinary_domain_share_one_key():
    a = compute_website_identity_key("https://acme.example/espresso-machine")
    b = compute_website_identity_key("https://acme.example/pour-over-kettle")
    assert a == b == "acme.example"


def test_identity_key_includes_the_handle_for_a_social_platform_host():
    assert compute_website_identity_key("https://www.instagram.com/acmecoffee/") == "instagram.com/acmecoffee"


def test_two_different_instagram_businesses_get_two_different_keys():
    a = compute_website_identity_key("https://www.instagram.com/acmecoffee/")
    b = compute_website_identity_key("https://www.instagram.com/beansupply/")
    assert a != b


def test_identity_key_falls_back_to_bare_host_for_a_social_platform_root():
    assert compute_website_identity_key("https://www.facebook.com/") == "facebook.com"


def test_identity_key_is_none_for_an_unparseable_url():
    assert compute_website_identity_key("not-a-url") is None
