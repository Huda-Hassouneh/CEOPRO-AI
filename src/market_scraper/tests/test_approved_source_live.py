"""One-request canary; opt in explicitly because CI must not depend on the internet."""

import os
import urllib.request

import pytest

from src.market_scraper.network_security import resolve_public_addresses

RUN_LIVE = os.getenv("RUN_MARKET_LIVE_TESTS") == "1"
URL = "https://books.toscrape.com/"


@pytest.mark.skipif(not RUN_LIVE, reason="RUN_MARKET_LIVE_TESTS=1 not set")
def test_approved_books_sandbox_is_reachable_and_still_identifies_as_sandbox():
    resolve_public_addresses(URL)
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "CEOPRO-MarketResearchBot/1.0 (bounded canary)"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read(250_000).decode("utf-8", errors="replace")
    assert response.status == 200
    assert "Books to Scrape" in body
    assert "We love being scraped" in body
