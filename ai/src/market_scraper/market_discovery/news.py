"""Industry and competitor news, for market trends.

Source: the GDELT DOC 2.0 API (api.gdeltproject.org) - an open, keyless
index of world news in 65 languages, free to use with attribution. It is
asked for recent articles from the company's country about its industry
(and, separately, naming its tracked competitors). GDELT asks for at most
one request every five seconds; a run sends at most two, and answers are
cached for a day (http.py).

Each article keeps its link, title, publisher and date; nothing is
summarised here. (Google News' RSS feed was considered and is not used:
its terms allow personal, non-commercial use only.)
GDELT_DOC_API_URL points at a mirror; DISCOVERY_DISABLE_NEWS=true turns
this source off.
"""
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from src.market_scraper.market_discovery.http import request_json

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
API_URL = os.getenv("GDELT_DOC_API_URL", "https://api.gdeltproject.org/api/v2/doc/doc")
TIMESPAN = os.getenv("DISCOVERY_NEWS_TIMESPAN", "3months")
MAX_RECORDS = 30
GDELT_INTERVAL_SECONDS = 5.5
# ISO country -> GDELT's source-country name.
COUNTRY_NAMES = {
    "JO": "jordan", "SA": "saudiarabia", "AE": "unitedarabemirates", "KW": "kuwait", "QA": "qatar", "BH": "bahrain",
    "OM": "oman", "EG": "egypt", "LB": "lebanon", "SY": "syria", "IQ": "iraq", "PS": "westbank", "YE": "yemen",
    "MA": "morocco", "DZ": "algeria", "TN": "tunisia", "LY": "libya", "SD": "sudan", "TR": "turkey", "US": "unitedstates",
    "GB": "unitedkingdom", "CA": "canada", "FR": "france", "DE": "germany", "IN": "india", "PK": "pakistan", "AU": "australia",
}
_UNSAFE = re.compile(r"[\"()]")


def available():
    if os.getenv("DISCOVERY_DISABLE_NEWS", "").lower() in ("1", "true", "yes"):
        return False, "disabled"
    return True, None


def _term(text: str) -> Optional[str]:
    text = _UNSAFE.sub(" ", text or "").strip()
    if len(text) < 3:  # GDELT rejects shorter words
        return None
    return f'"{text}"' if " " in text else text


def build_query(terms: List[str], country_code: Optional[str]) -> Optional[str]:
    words = [t for t in dict.fromkeys(_term(t) for t in terms) if t][:8]
    if not words:
        return None
    query = words[0] if len(words) == 1 else "(" + " OR ".join(words) + ")"
    country = COUNTRY_NAMES.get((country_code or "").upper())
    return f"{query} sourcecountry:{country}" if country else query


def _date(value: Optional[str]) -> Optional[str]:
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def parse(payload) -> List[dict]:
    out, seen = [], set()
    for article in (payload or {}).get("articles") or []:
        url, title = article.get("url"), (article.get("title") or "").strip()
        if not url or not title or not url.startswith(("https://", "http://")) or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "title": title[:300], "source_domain": (article.get("domain") or "")[:255] or None,
                    "language": article.get("language"), "published_at": _date(article.get("seendate"))})
    return out


def search(terms: List[str], country_code: Optional[str], sleep=time.sleep) -> List[dict]:
    """Raises httpx.HTTPError / ValueError when GDELT can't be reached.
    GDELT answers 429 when the five-second rule was broken from the same
    address (a shared server can share it with others): wait and ask once more."""
    query = build_query(terms, country_code)
    if query is None:
        return []
    params = {"query": query, "mode": "ArtList", "format": "json",
              "maxrecords": MAX_RECORDS, "timespan": TIMESPAN, "sort": "DateDesc"}
    for attempt in range(2):
        try:
            payload = request_json("GET", API_URL, params=params, timeout=20, cache_key_extra="news")
            return parse(payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 429 or attempt:
                raise
            sleep(GDELT_INTERVAL_SECONDS * 2)
    return []


def collect(industry_terms: List[str], competitor_names: List[str], country_code: Optional[str], sleep=time.sleep) -> dict:
    """{"articles": [... with topic], "requests", "answered", "status"}"""
    ok, reason = available()
    if not ok:
        return {"articles": [], "requests": 0, "answered": 0, "status": "skipped", "reason": reason}
    articles, requests, answered = [], 0, 0
    for topic, terms in (("industry", industry_terms), ("competitor", competitor_names)):
        if not [t for t in terms if _term(t)]:
            continue
        if requests:
            sleep(GDELT_INTERVAL_SECONDS)  # GDELT's one-request-per-five-seconds rule
        requests += 1
        try:
            found = search(terms, country_code, sleep=sleep)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("news search failed: %s", type(exc).__name__)
            continue
        answered += 1
        for article in found:
            if topic == "competitor":
                lowered = article["title"].lower()
                article["competitor"] = next((n for n in competitor_names if n and n.lower() in lowered), None)
                if article["competitor"] is None:
                    continue  # mentions none of them in its headline: not about a competitor
            articles.append({**article, "topic": topic})
    status = "ok" if answered else ("failed" if requests else "skipped")
    return {"articles": articles, "requests": requests, "answered": answered, "status": status,
            "reason": None if answered or not requests else "unreachable"}
