"""
Targeted public research for one question.

Used when the evidence a question needs is not in the company's own
records: why customers prefer a product, who else sells it, what the
market is doing, what a regulation, tax or customs rule says. The steps:

1. queries: a few searches written for the specific need, in the
   question's language and English, naming the country, product and HS
   code when known; regulatory and trade questions also search the
   official authorities' own sites first. A query never carries the
   company's private figures - amounts and quantities are removed.
2. search: through the configured search provider (market_scraper/
   web_search.py), within a daily budget shared by the whole server and a
   smaller one per company.
3. read: the result pages themselves (page_reader.py) - not just the
   search engine's snippet - preferring official sources for legal
   matters. Pages are cached as public data, never with any company link.
4. passages: the parts of each page that best match the question become
   evidence items, each carrying its page's URL, publisher, dates and
   any known limitation.

Every outcome is explicit: research not set up, budget used, search
failed, nothing found, pages unreadable. None of them is ever presented
as "the information does not exist".
"""
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from src.ai.rag import evidence as ev
from src.ai.rag.bm25_index import BM25Index
from src.ai.research import page_reader, sources
from src.ai.billing import credits

logger = logging.getLogger("KEEL_RESEARCH")

DAILY_SEARCH_LIMIT = int(os.getenv("RESEARCH_DAILY_SEARCH_LIMIT", "30"))
TENANT_DAILY_SEARCH_LIMIT = int(os.getenv("RESEARCH_TENANT_DAILY_SEARCH_LIMIT", "12"))
MAX_QUERIES = 3
MAX_RESULTS_PER_QUERY = 6
MAX_PAGES = int(os.getenv("RESEARCH_MAX_PAGES", "4"))
PASSAGES_PER_PAGE = 2
PASSAGE_WORDS = 110
RETENTION_DAYS = int(os.getenv("RESEARCH_PAGE_RETENTION_DAYS", "30"))
_CACHE_TTL = {"regulation": timedelta(days=7), "default": timedelta(days=3), "failure": timedelta(hours=1)}

# status of the research step as a whole
NOT_NEEDED = "not_needed"
NOT_CONFIGURED = "not_configured"
BUDGET_EXHAUSTED = "budget_exhausted"
SEARCH_FAILED = "search_failed"
NO_RESULTS = "no_results"
UNREADABLE = "pages_unreadable"
FOUND = "found"

_OFFICIAL_SITES = {
    "JO": ("customs.gov.jo", "istd.gov.jo", "jfda.jo", "jsmo.gov.jo"),
    "SA": ("zatca.gov.sa", "sfda.gov.sa", "saso.gov.sa"),
    "AE": ("tax.gov.ae", "u.ae", "moiat.gov.ae"),
    "EG": ("customs.gov.eg", "eta.gov.eg"),
    "TR": ("ticaret.gov.tr",),
}
COUNTRY_NAMES = {
    "JO": ("Jordan", "الأردن"), "SA": ("Saudi Arabia", "السعودية"), "AE": ("United Arab Emirates", "الإمارات"),
    "KW": ("Kuwait", "الكويت"), "QA": ("Qatar", "قطر"), "BH": ("Bahrain", "البحرين"), "OM": ("Oman", "عُمان"),
    "EG": ("Egypt", "مصر"), "LB": ("Lebanon", "لبنان"), "IQ": ("Iraq", "العراق"), "PS": ("Palestine", "فلسطين"),
    "MA": ("Morocco", "المغرب"), "DZ": ("Algeria", "الجزائر"), "TN": ("Tunisia", "تونس"), "TR": ("Türkiye", "تركيا"),
    "CN": ("China", "الصين"), "IN": ("India", "الهند"), "US": ("United States", "الولايات المتحدة"),
    "GB": ("United Kingdom", "المملكة المتحدة"), "DE": ("Germany", "ألمانيا"), "IT": ("Italy", "إيطاليا"),
}
_PRIVATE_FIGURES = re.compile(
    r"(?:[$€£₺⃁]\s*)?\d[\d,.]*\s*(?:%|units?|pieces?|pcs|cartons?|boxes?|kg|tons?|jod|sar|aed|kwd|qar|bhd|omr|egp|"
    r"try|usd|eur|gbp|lira|dinars?|riyals?|dirhams?|dollars?|euros?|دينار|ريال|درهم|جنيه|ليرة|دولار|يورو|وحدة|قطعة|كرتونة|طن|كيلو)?",
    re.IGNORECASE,
)
_EMAIL_OR_PHONE = re.compile(r"\S+@\S+|\+?\d[\d\s-]{7,}\d")


_LIMITS = {
    "undated": ("the page does not state when it was published or last updated",
                "الصفحة لا تذكر تاريخ نشرها أو آخر تحديث لها"),
    "snippet": ("the page itself could not be read ({reason}); this is only the search engine's summary of it",
                "تعذّرت قراءة الصفحة نفسها ({reason})؛ هذا ملخص محرك البحث لها فقط"),
}


def _limit(key: str, language: str, **values) -> str:
    english, arabic = _LIMITS[key]
    return (arabic if language == "ar" else english).format(**values)


@dataclass
class ResearchResult:
    status: str
    queries: List[str] = field(default_factory=list)
    evidence: List[ev.Evidence] = field(default_factory=list)
    pages: List[dict] = field(default_factory=list)
    detail: Optional[str] = None

    def summary(self) -> dict:
        return {"status": self.status, "queries": self.queries, "pages": self.pages, "detail": self.detail}


def public_safe(query: str, hs_code: Optional[str] = None) -> str:
    """A search query with the company's private figures, emails and phone numbers removed."""
    text = _EMAIL_OR_PHONE.sub(" ", query or "")
    text = _PRIVATE_FIGURES.sub(lambda m: m.group(0) if hs_code and hs_code in re.sub(r"\D", "", m.group(0))
                                else " ", text)
    return re.sub(r"\s+", " ", text).strip(" ?؟.!,")


def _is_arabic(text: str) -> bool:
    return bool(re.search(r"[؀-ۿ]", text or ""))


def plan_queries(question: str, intents: List[str], slots: dict, company: dict,
                 ask: Optional[Callable] = None) -> List[str]:
    """Search queries for this question; the configured model writes them
    when available (better wording, both languages), otherwise templates."""
    country = slots.get("destination_country") or (slots.get("countries") or [None])[0] or company.get("country_code")
    product = ", ".join(p["name"] for p in slots.get("products") or []) or None
    hs_code = slots.get("hs_code")
    planned: List[str] = []
    if ask is not None:
        try:
            answer = ask([
                {"role": "system", "content": (
                    "You write web search queries for a business researcher. Answer with only JSON "
                    "{\"queries\": [\"...\"]}: at most 3 short, specific queries that would find primary or "
                    "official sources answering the question. Name the country, product and HS code when known. "
                    "For a legal, tax, customs or trade question make at least one query aim at the official "
                    "authority. If the question is in Arabic, write one query in Arabic and one in English. "
                    "Never include prices, quantities, amounts or any private business figure.")},
                {"role": "user", "content": json.dumps({
                    "question": public_safe(question, hs_code), "needs": intents, "country": country,
                    "origin_country": slots.get("origin_country"), "product": product, "hs_code": hs_code,
                    "business_type": company.get("business_type")}, ensure_ascii=False)},
            ], temperature=0, max_tokens=500)
            parsed = json.loads(re.search(r"\{.*\}", answer, re.S).group(0))
            planned = [public_safe(q, hs_code) for q in parsed.get("queries") or [] if isinstance(q, str)]
        except Exception as exc:  # noqa: BLE001 - templates still give useful queries
            logger.info("research query planning unavailable: %s", type(exc).__name__)
    if not planned:
        planned = _template_queries(question, intents, country, slots.get("origin_country"), product, hs_code,
                                    company.get("business_type"))
    if country in _OFFICIAL_SITES and ({"regulation", "trade", "landed_cost"} & set(intents)):
        topic = product or hs_code or public_safe(question, hs_code)
        planned.append(f"site:{_OFFICIAL_SITES[country][0]} {topic}")
    return list(dict.fromkeys(q for q in planned if q and len(q) >= 4))[:MAX_QUERIES]


def _template_queries(question: str, intents: List[str], country: Optional[str], origin: Optional[str],
                      product: Optional[str], hs_code: Optional[str], business_type: Optional[str]) -> List[str]:
    english, arabic = COUNTRY_NAMES.get(country, (country or "", country or ""))
    subject = product or public_safe(question, hs_code)
    queries = []
    if {"trade", "landed_cost"} & set(intents):
        origin_name = COUNTRY_NAMES.get(origin, (origin or "",))[0]
        queries.append(f"{subject} import customs duty {english} {('HS ' + hs_code) if hs_code else 'HS code'}".strip())
        queries.append(f"import requirements {english} {subject} {('from ' + origin_name) if origin_name else ''}".strip())
        if _is_arabic(question):
            queries.append(f"رسوم جمركية استيراد {subject} {arabic}")
    elif "regulation" in intents:
        queries.append(f"{public_safe(question, hs_code)} {english} official requirements")
    else:
        queries.append(f"{public_safe(question, hs_code)} {english}".strip())
        if business_type and product:
            queries.append(f"{product} customer reviews {english}")
    return queries


def _tenant_budget_ok(tenant_id: str) -> bool:
    try:
        from src.ai.core.redis_client import get_redis_client

        client = get_redis_client(socket_connect_timeout=0.5, socket_timeout=0.5)
        key = f"keel:research:{tenant_id}:{datetime.now(timezone.utc).date().isoformat()}"
        used = client.incr(key)
        client.expire(key, 2 * 86400)
        return used <= TENANT_DAILY_SEARCH_LIMIT
    except Exception:  # noqa: BLE001 - the server-wide database budget still applies
        return True


def _search(conn, tenant_id: str, query: str, country: Optional[str], search_fn) -> List[dict]:
    from src.market_scraper import search_quota, web_search

    if search_fn is None:
        if not web_search.is_configured():
            raise _Stop(NOT_CONFIGURED)
        if not search_quota.has_budget(conn, DAILY_SEARCH_LIMIT) or not _tenant_budget_ok(tenant_id):
            raise _Stop(BUDGET_EXHAUSTED)
        search_quota.record_query(conn)
        conn.commit()
        try:
            _provider, results = web_search.search(query, MAX_RESULTS_PER_QUERY, country=country)
        except web_search.SearchFailed as exc:
            raise _Stop(SEARCH_FAILED, str(exc)) from exc
        return [r.as_dict() for r in results]
    return search_fn(query)


class _Stop(Exception):
    def __init__(self, status: str, detail: Optional[str] = None):
        super().__init__(status)
        self.status, self.detail = status, detail


def _normalize_url(url: str) -> str:
    return re.sub(r"#.*$", "", (url or "").strip())


def _cached_page(conn, url: str, purpose: str) -> Optional[page_reader.Page]:
    if conn is None:
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status, final_url, title, site_name, published_at, modified_at, language, page_text, fetched_at "
                "FROM research_pages WHERE url = %s;", (url,))
            row = cursor.fetchone()
    except Exception:  # noqa: BLE001 - the cache is an optimisation only
        conn.rollback()
        return None
    if not row:
        return None
    status, final_url, title, site_name, published, modified, language, text, fetched_at = row
    ttl = _CACHE_TTL["failure"] if status != page_reader.OK else _CACHE_TTL.get(purpose, _CACHE_TTL["default"])
    if fetched_at is None or datetime.now(timezone.utc) - fetched_at > ttl:
        return None
    return page_reader.Page(url=url, status=status, final_url=final_url, title=title, site_name=site_name,
                            published_at=published, modified_at=modified, language=language, text=text or "",
                            retrieved_at=fetched_at.isoformat())


def _store_page(conn, page: page_reader.Page) -> None:
    if conn is None:
        return
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO research_pages (url, status, final_url, title, site_name, published_at, modified_at,
                                            language, page_text, content_hash, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (url) DO UPDATE SET status = EXCLUDED.status, final_url = EXCLUDED.final_url,
                    title = EXCLUDED.title, site_name = EXCLUDED.site_name, published_at = EXCLUDED.published_at,
                    modified_at = EXCLUDED.modified_at, language = EXCLUDED.language, page_text = EXCLUDED.page_text,
                    content_hash = EXCLUDED.content_hash, fetched_at = EXCLUDED.fetched_at;
                """,
                (page.url, page.status, page.final_url, (page.title or "")[:500] or None, (page.site_name or "")[:200] or None,
                 page.published_at, page.modified_at, (page.language or "")[:20] or None, page.text,
                 hashlib.sha256(page.text.encode("utf-8")).hexdigest() if page.text else None),
            )
            # Pages are only a cache: anything older than the retention window is dropped.
            cursor.execute("DELETE FROM research_pages WHERE fetched_at < CURRENT_TIMESTAMP - %s * INTERVAL '1 day';",
                           (RETENTION_DAYS,))
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - never fail a question over the cache
        logger.info("research page not cached: %s", type(exc).__name__)
        conn.rollback()


def _passages(page: page_reader.Page) -> List[str]:
    words = page.text.split()
    passages = [" ".join(words[start:start + PASSAGE_WORDS])
                for start in range(0, max(len(words), 1), PASSAGE_WORDS - 30) if words[start:start + PASSAGE_WORDS]]
    return passages + list(page.tables)


def _best_passages(page: page_reader.Page, query: str, limit: int = PASSAGES_PER_PAGE) -> List[str]:
    candidates = _passages(page)
    if not candidates:
        return []
    index = BM25Index([(str(i), text) for i, text in enumerate(candidates)])
    ranked = index.query(query, top_k=limit)
    return [chunk.text for chunk in ranked]


def _order_results(results: List[dict], official_first: bool) -> List[dict]:
    seen, ordered = set(), []
    for result in results:
        host = sources.host_of(result["url"])
        if not host or host in seen:
            continue
        seen.add(host)
        ordered.append(result)
    if official_first:
        ordered.sort(key=lambda r: sources.credibility(r["url"]) != sources.OFFICIAL)
    return ordered


def _page_evidence(registry: ev.EvidenceRegistry, page: page_reader.Page, passages: List[str], result: dict,
                   now: str, language: str = "en") -> List[ev.Evidence]:
    url = page.final_url or page.url
    credibility = ev.OFFICIAL if sources.credibility(url) == sources.OFFICIAL else ev.SECONDARY
    limitations = []
    if not page.published_at and not page.modified_at:
        limitations.append(_limit("undated", language))
    added = []
    for passage in passages:
        added.append(registry.add(
            ev.WEB_PAGE, page.title or result.get("title") or sources.host_of(url), passage, credibility, ev.EXTRACTED,
            organisation=sources.organisation(url, page.site_name), url=url,
            published_at=page.published_at, effective_at=None, observed_at=None,
            retrieved_at=page.retrieved_at or now, jurisdiction=sources.jurisdiction(url),
            limitations=list(limitations)))
    return added


@credits.metered("web_research")
def research(conn, tenant_id: str, registry: ev.EvidenceRegistry, question: str, intents: List[str], slots: dict,
             company: dict, ask: Optional[Callable] = None, search_fn: Optional[Callable] = None,
             fetch: Optional[Callable] = None, resolver=None, language: str = "en") -> ResearchResult:
    """Researches `question` and adds what was found to `registry`.
    `search_fn(query) -> [{url, title, snippet}]`, `fetch` and `resolver`
    replace the real search provider and network in tests."""
    now = datetime.now(timezone.utc).isoformat()
    purpose = "regulation" if {"regulation", "trade", "landed_cost"} & set(intents) else "default"
    reading_query = f"{question} {' '.join(p['name'] for p in slots.get('products') or [])}"
    result = ResearchResult(status=NO_RESULTS)

    # Links the user pasted are read directly: no search needed, no budget used.
    candidates: List[dict] = [{"url": url, "title": url, "snippet": "", "user_link": True} for url in slots.get("urls") or []]
    queries = plan_queries(question, intents, slots, company, ask)
    result.queries = queries
    country = slots.get("destination_country") or company.get("country_code")
    for query in queries:
        try:
            candidates.extend(_search(conn, tenant_id, query, country, search_fn))
        except _Stop as stop:
            if not candidates:
                result.status, result.detail = stop.status, stop.detail
                return result
            break
    ordered = _order_results(candidates, official_first=purpose == "regulation")
    if not ordered:
        return result

    readable = 0
    for item in ordered[:MAX_PAGES]:
        url = _normalize_url(item["url"])
        page = _cached_page(conn, url, purpose)
        if page is None:
            page = page_reader.read(url, fetch=fetch, resolver=resolver)
            _store_page(conn, page)
        entry = {"url": url, "title": page.title or item.get("title"), "status": page.status,
                 "credibility": sources.credibility(url)}
        if page.readable:
            passages = _best_passages(page, reading_query)
            if passages:
                readable += 1
                entry["evidence_ids"] = [e.id for e in _page_evidence(registry, page, passages, item, now, language)]
                result.evidence.extend(registry.get(i) for i in entry["evidence_ids"])
        elif item.get("snippet"):
            # The search engine's own summary, clearly marked as such.
            snippet = registry.add(
                ev.WEB_PAGE, item.get("title") or sources.host_of(url), item["snippet"],
                ev.OFFICIAL if sources.credibility(url) == sources.OFFICIAL else ev.SECONDARY, ev.EXTRACTED,
                organisation=sources.host_of(url), url=url, retrieved_at=now, jurisdiction=sources.jurisdiction(url),
                limitations=[_limit("snippet", language, reason=page.status.replace("_", " "))])
            entry["evidence_ids"] = [snippet.id]
            result.evidence.append(snippet)
        result.pages.append(entry)
    result.status = FOUND if result.evidence else UNREADABLE
    if result.evidence and not readable:
        result.detail = "only search summaries were available; no page could be read"
    return result
