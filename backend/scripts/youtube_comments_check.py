"""One live check of the YouTube comment collector (PENDING_ACTIONS #121).

Usage, from backend/:
    YOUTUBE_API_KEY=<key> PYTHONPATH=. python scripts/youtube_comments_check.py "<competitor name>" "<city>"

Prints how many comments (and replies) survived the collector's filters and two samples. Reads the key from the
environment only; nothing is stored or sent anywhere but YouTube. One run costs about 100-200 quota units.
"""
import json
import os
import sys

from src.market_scraper import competitor_mentions as mentions


def main() -> None:
    if len(sys.argv) < 2 or not os.environ.get("YOUTUBE_API_KEY"):
        sys.exit(__doc__)
    name, hint = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
    comments = mentions.youtube_comments(name, hint, os.environ["YOUTUBE_API_KEY"])
    print(len(comments), "comments;", sum(1 for c in comments if c["parent_external_id"]), "replies")
    print(json.dumps(comments[:2], indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
