"""
Live-verifies candidate retailer domains for a direct_search.py vertical -
robots.txt on the homepage, a real schema.org SearchAction, robots.txt on
the resulting search path. Only a domain that passes all three is safe to
add to RETAILER_DOMAINS_BY_VERTICAL - this script is how you find out
which ones do, rather than guessing well-known retailer names into the
dict (the exact anti-pattern that module's own docstring warns against).

Run from the repo root:
    python scripts/live_verify_retailer_domains.py

Edit CANDIDATE_DOMAINS below for a different vertical/candidate list.
Needs normal outbound internet - this is a real network operation against
real third-party sites, so keep the delay reasonable and don't run it
against a huge candidate list casually.
"""
import time

from src.market_scraper.direct_search import _fetch, discover_search_url_template, build_search_url
from src.market_scraper.discovery import _fetch_robots_allows

TEST_PRODUCT = "Arduino Uno R3"
DELAY_SECONDS = 1.0

CANDIDATE_DOMAINS = [
    "www.digikey.com",
    "www.mouser.com",
    "www.robotshop.com",
    "www.seeedstudio.com",
    "www.jameco.com",
    "www.newark.com",
    "www.pololu.com",
    "www.microcenter.com",
    "www.makershed.com",
    "www.electromaker.io",
    "www.dfrobot.com",
    "www.tinkersphere.com",
]


def verify(domain: str) -> dict:
    result = {"domain": domain, "status": "FAIL", "reason": None, "template": None}
    homepage = f"https://{domain}/"

    robots_home = _fetch_robots_allows(homepage)
    if robots_home is not True:
        result["reason"] = f"robots.txt disallows (or unreadable for) homepage: {robots_home}"
        return result

    html = _fetch(homepage)
    if not html:
        result["reason"] = "homepage fetch failed (network error, bot-block, or non-200)"
        return result

    template = discover_search_url_template(html)
    if not template:
        result["reason"] = "no schema.org SearchAction found on homepage"
        return result
    result["template"] = template

    search_url = build_search_url(template, TEST_PRODUCT)
    robots_search = _fetch_robots_allows(search_url)
    if robots_search is not True:
        result["reason"] = f"robots.txt disallows (or unreadable for) the search path: {robots_search}"
        return result

    result["status"] = "PASS"
    result["reason"] = "homepage + search path both robots-allowed, real SearchAction found"
    return result


if __name__ == "__main__":
    results = []
    for domain in CANDIDATE_DOMAINS:
        r = verify(domain)
        print(f"[{r['status']}] {domain:30} {r['reason']}")
        if r["template"]:
            print(f"       template: {r['template']}")
        results.append(r)
        time.sleep(DELAY_SECONDS)

    passing = [r["domain"] for r in results if r["status"] == "PASS"]
    print(f"\n{len(passing)}/{len(CANDIDATE_DOMAINS)} candidates passed live verification:")
    print(passing)
