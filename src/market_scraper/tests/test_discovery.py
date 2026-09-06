from src.market_scraper.discovery import CandidateSource, looks_like_manufacturer_or_wholesale


def test_flags_a_candidate_whose_domain_matches_the_brand():
    candidate = CandidateSource(product_name="Arduino Nano", url="https://arduino.cc/store/nano", title="Buy Nano")
    assert looks_like_manufacturer_or_wholesale(candidate, brand_tokens={"arduino"}) is True


def test_does_not_flag_a_third_party_retailer():
    candidate = CandidateSource(product_name="Arduino Nano", url="https://sparkfun.com/products/nano", title="Arduino Nano - SparkFun")
    assert looks_like_manufacturer_or_wholesale(candidate, brand_tokens={"arduino"}) is False


def test_flags_a_wholesale_signal_word_in_the_title():
    candidate = CandidateSource(product_name="Widget", url="https://example.com/item", title="Widget - Wholesale Distributor Pricing")
    assert looks_like_manufacturer_or_wholesale(candidate, brand_tokens=set()) is True
