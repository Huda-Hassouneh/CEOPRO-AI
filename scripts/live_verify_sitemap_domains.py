"""
Live-verifies candidate domains for sitemap_discovery.py's
SITEMAP_DOMAINS_BY_VERTICAL - real robots.txt check, real sitemap fetch
(via robots.txt's own Sitemap: directive or the conventional
/sitemap.xml path), real XML parse, and a real product-URL match against
a real test query. Only a domain that passes all of it is safe to add -
same discipline scripts/live_verify_retailer_domains.py already
established for RETAILER_DOMAINS_BY_VERTICAL, applied to this module's
different mechanism.

Candidates below are exactly the domains this session's own
live_verify_retailer_domains.py run already found robots.txt-allowed but
with no schema.org SearchAction (see direct_search.py's own docstring)
- real candidates for sitemap-based discovery instead, not a fresh guess,
but their sitemap.xml existence has NOT been checked yet - that's what
this script is for.

Run from the repo root:
    python scripts/live_verify_sitemap_domains.py

Needs normal outbound internet - real network operations against real
third-party sites.
"""
import time

from src.market_scraper.discovery import _fetch_robots_allows
from src.market_scraper.sitemap_discovery import discover_products_via_sitemap

TEST_PRODUCT = "Arduino Uno R3"
DELAY_SECONDS = 1.0

CANDIDATE_DOMAINS = [
    "www.seeedstudio.com",
    "www.pololu.com",
    "www.electromaker.io",
]


def verify(domain: str) -> dict:
    result = {"domain": domain, "status": "FAIL", "reason": None, "candidates": []}

    if _fetch_robots_allows(f"https://{domain}/") is not True:
        result["reason"] = "robots.txt disallows (or unreadable for) the domain root"
        return result

    candidates = discover_products_via_sitemap(domain, TEST_PRODUCT, limit=5)
    if not candidates:
        result["reason"] = "no sitemap found, or no URL in it matched the test product closely enough"
        return result

    result["status"] = "PASS"
    result["reason"] = f"sitemap found, {len(candidates)} real candidate URL(s) matched"
    result["candidates"] = [c.url for c in candidates]
    return result


if __name__ == "__main__":
    results = []
    for domain in CANDIDATE_DOMAINS:
        r = verify(domain)
        print(f"[{r['status']}] {domain:30} {r['reason']}")
        for url in r["candidates"]:
            print(f"       candidate: {url}")
        results.append(r)
        time.sleep(DELAY_SECONDS)

    passing = [r["domain"] for r in results if r["status"] == "PASS"]
    print(f"\n{len(passing)}/{len(CANDIDATE_DOMAINS)} candidates passed live verification:")
    print(passing)
    print("\nOnly these are safe to add to sitemap_discovery.py's SITEMAP_DOMAINS_BY_VERTICAL - "
          "send me this full output and I'll wire the passing ones into the codebase.")
