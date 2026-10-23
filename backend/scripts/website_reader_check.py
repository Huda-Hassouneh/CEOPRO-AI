"""
Checks that competitor websites can be read FROM THIS MACHINE - run it on the
deployed service (Render shell), not on a laptop: sites block by address and
by User-Agent, so only the server's own answer counts.

It reads each site with the real reader (src/market_scraper/market_discovery/
intel.py: robots.txt, the KEEL User-Agent, the same status codes) and prints
the outcome and HTTP status per site. Nothing is stored.

Usage (from backend/):
    python -m scripts.website_reader_check https://example-shop.com https://other.jo
    python -m scripts.website_reader_check --db            # websites of tracked competitors (needs DATABASE_URL)
    python -m scripts.website_reader_check --db --limit 20

Exit code 1 when more than half of the sites refused the reader
(refused_by_site): the server's address or MARKET_RESEARCH_USER_AGENT is being
blocked broadly, which no retry fixes. See docs/INSTALLATION.md, "Troubleshooting".
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.market_scraper.market_discovery import intel  # noqa: E402

REFUSED_SHARE_LIMIT = 0.5


def tracked_websites(limit: int) -> list:
    import psycopg2

    conn = psycopg2.connect(os.environ["DATABASE_URL"].replace("+asyncpg", ""))
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT gc.website_url FROM tenant_competitors tc "
                "JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id "
                "WHERE gc.website_url IS NOT NULL AND gc.website_url <> '' LIMIT %s;",
                (limit,),
            )
            return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def check(urls, collect=intel.collect) -> int:
    outcomes = Counter()
    for url in urls:
        try:
            result = collect(url)
            status, code = result.get("status") or ("ok" if result["pages_read"] else "empty"), result.get("http_status")
        except Exception as exc:  # noqa: BLE001 - one bad site must not stop the check
            status, code = "extraction_failed", type(exc).__name__
        outcomes[status] += 1
        print(f"  {status:<22} {code or '':<6} {url}")
    total = sum(outcomes.values())
    print(f"User-Agent: {intel.USER_AGENT}")
    print("Summary: " + (", ".join(f"{name} {count}" for name, count in outcomes.most_common()) or "no sites"))
    refused = outcomes[intel.STATUS_REFUSED]
    if total and refused / total > REFUSED_SHARE_LIMIT:
        print(f"{refused} of {total} sites refused the reader: this server's address or User-Agent is blocked broadly.")
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check that competitor websites can be read from this machine.")
    parser.add_argument("urls", nargs="*", help="websites to read")
    parser.add_argument("--db", action="store_true", help="also read the websites of tracked competitors")
    parser.add_argument("--limit", type=int, default=10, help="how many tracked competitors with --db (default 10)")
    args = parser.parse_args(argv)
    urls = list(args.urls) + (tracked_websites(args.limit) if args.db else [])
    if not urls:
        parser.error("give at least one website, or --db")
    print(f"Reading {len(urls)} website(s) from this machine")
    return check(urls)


if __name__ == "__main__":
    sys.exit(main())
