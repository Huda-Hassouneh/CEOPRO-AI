"""
KEEL - Confidence-Gated Web Search Fallback for the RAG Chatbot.

The one real gap the RAG engine had before this: run_retrieval() only
ever queries this tenant's own persisted rag_document_chunks - when a
question genuinely isn't covered by anything ingested yet (no matching
document AND no matching structured fact), answer_query() had no option
but to have the LLM decline gracefully, forever. That's the right default
(never guessing from a model's own unverified general knowledge), but a
real business question about the tenant's own market/field sometimes has
a genuinely findable answer on the open web - this module is that last
resort, gated hard enough that it only ever helps, never degrades the
"never guess" guarantee the rest of this pipeline already has.

Reuses search_quota.py's Postgres-backed daily budget tracker (the same
zero-dollar-overage mechanism market_scraper/web_product_discovery.py
already uses for competitor discovery) so this shares one governed daily
budget with that module rather than opening a second, ungoverned spend
path against the same paid search allowance. Deliberately does
NOT reuse web_product_discovery.py's own cache/candidate-source machinery
beyond that: that module's cache key is a competitor-discovery product
query and its CandidateSource shape has no room for a search snippet,
which this module genuinely needs (a bare title/URL isn't enough context
for an LLM to ground a real answer in) - a real, justified reason for a
second, small implementation, not duplication for its own sake.

The confidence gate, layered (every layer has to pass before a single
live web call is even made):
1. looks_like_answerable_question() - a cheap, explainable, non-LLM check
   that rejects a bare greeting/thanks or a query too short to search
   with. Never fires on the exact greeting examples SYSTEM_PROMPT itself
   already lists ('hi', 'مرحبا', 'كيفك', 'شعلومك', ...) - those already
   get a real, warm answer with zero search cost.
2. Called by answer_query() ONLY when both retrieval and the live
   structured-facts block already came back genuinely empty - a search is
   never attempted "just in case" on a question this tenant's own data
   could already answer.
3. The query itself is scoped to the tenant's own field (companies.
   business_type/country_code appended) - never a bare, unscoped web
   query, so this can't wander into general trivia even if a caller
   somehow got here with an off-topic question.
4. MIN_SOURCES_REQUIRED distinct results required before anything is
   handed to the LLM at all - a single, uncorroborated result is not
   "highly accurate, well-processed" evidence for a real business answer,
   it's one unverified page. Fewer than that: build_web_fallback_context()
   returns ("", []), exactly as if no fallback had been attempted, and
   SYSTEM_PROMPT's existing honest-decline behavior applies unchanged.

Never fabricates a result: no configured provider, a request failure, or
genuinely fewer than MIN_SOURCES_REQUIRED results all return ("", []) -
the same honest-degradation contract every other discovery module in this
codebase already follows (see web_product_discovery.py/searxng_
discovery.py's own docstrings for the same pattern).

Setup: the search provider is configuration in market_scraper/
web_search.py (WEB_SEARCH_PROVIDERS plus that provider's key, e.g.
BRAVE_SEARCH_API_KEY or TAVILY_API_KEY, or SEARXNG_INSTANCE_URL for a
self-hosted instance) - the same settings competitor discovery uses.
"""
import logging
import os
from typing import List, Optional, Tuple

from src.market_scraper import search_quota, web_search

logger = logging.getLogger("CEOPRO_AI_RAG_WEB_FALLBACK")


# A single, uncorroborated web result is never handed to the LLM as
# "external evidence" for a real business question - see this module's
# own docstring, gate layer 4.
MIN_SOURCES_REQUIRED = 2
_MAX_RESULTS = 5
_DEFAULT_DAILY_QUERY_LIMIT = int(os.getenv("RAG_WEB_FALLBACK_DAILY_LIMIT", "50"))

# Real, explicit greeting/small-talk/thanks phrases - the exact same
# vocabulary SYSTEM_PROMPT's own "Proportionality" paragraph already
# names as getting a short, warm reply with no data lookup at all. A web
# search is never worth attempting for these: there is nothing to search
# for, and burning real search quota on "hi" would starve a later,
# genuine question the same day.
_GREETING_AND_SMALLTALK = {
    "hi", "hello", "hey", "hiya", "yo", "hi there", "hello there",
    "thanks", "thank you", "thx", "ok thanks", "okay thanks",
    "how are you", "how's it going", "what's up", "whats up",
    "مرحبا", "مرحبأ", "هاي", "هلا", "هلا والله", "أهلا", "اهلا", "اهلين",
    "كيفك", "كيفك؟", "شو اخبارك", "ازيك", "ازيك؟", "عامل ايه", "شعلومك", "شعلومك؟",
    "شكرا", "شكرا لك", "شكرا جزيلا", "مشكور", "يعطيك العافية", "تسلم",
    "مساء الخير", "صباح الخير", "مساء النور", "صباح النور",
}


def looks_like_answerable_question(query_text: str) -> bool:
    """
    A cheap, explainable gate (not a second LLM call) - the web fallback
    is expensive (real API quota, real latency), so this must never fire
    for a bare greeting or a fragment too short to build a real search
    query from. Deliberately errs toward NOT searching: a false negative
    here just means SYSTEM_PROMPT's existing honest-decline behavior
    applies, same as today; a false positive would burn real search quota
    on something that was never going to be answerable anyway.
    """
    normalized = (query_text or "").strip().lower()
    if not normalized:
        return False
    if normalized.strip("!؟?. ") in _GREETING_AND_SMALLTALK:
        return False
    word_count = len(normalized.split())
    if word_count < 3 and len(normalized) < 12:
        return False
    return True


def _load_tenant_business_context(conn, tenant_id: str) -> dict:
    """Real, already-collected tenant fields used only to SCOPE the search
    query to this tenant's own field/region - never sent anywhere as a
    credential, never used to widen the search beyond the tenant's own
    business. Returns {} (never raises) if the tenant row is somehow
    unavailable - the caller still gets a usable, if less-scoped, query."""
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT business_name, business_type, country_code FROM companies WHERE tenant_id = %s;",
                (tenant_id,),
            )
            row = cursor.fetchone()
    except Exception as e:  # noqa: BLE001 - a scoping lookup must never fail the whole fallback
        logger.warning("could not load tenant business context for web fallback (tenant=%s): %s", tenant_id, e)
        return {}
    if not row:
        return {}
    business_name, business_type, country_code = row
    return {"business_name": business_name, "business_type": business_type, "country_code": country_code}


def _build_scoped_query(query_text: str, business: dict) -> str:
    parts = [query_text, business.get("business_type"), business.get("country_code")]
    return " ".join(part for part in parts if part)


_FREE = ("searxng",)
_PAID = tuple(p for p in web_search.PROVIDERS if p not in _FREE)


def _search_paid(conn, query: str, max_results: int) -> Optional[List[dict]]:
    """Results from the configured paid search provider(s) - a list
    (possibly empty: a real, cacheable "no results" answer) - or None when
    none is configured, today's budget is used, or every one failed, so
    the caller knows to try the free self-hosted search next. Quota is
    checked BEFORE the call and a real call is recorded (committed) the
    moment it's made - the same discipline web_product_discovery.py's own
    _with_cache_and_fallback() documents."""
    if not web_search.is_configured(exclude=_FREE):
        logger.info("No paid web-search provider configured - trying the self-hosted search for RAG research.")
        return None
    if not search_quota.has_budget(conn, _DEFAULT_DAILY_QUERY_LIMIT):
        logger.info("Daily RAG web-fallback search budget already used - trying the self-hosted search.")
        return None
    search_quota.record_query(conn)
    conn.commit()
    try:
        _, results = web_search.search(query, max_results, exclude=_FREE)
    except web_search.SearchFailed as e:
        logger.warning("RAG web-fallback search failed: %s", e)
        return None
    return [r.as_dict() for r in results]


def _search_free(query: str, max_results: int) -> List[dict]:
    """The self-hosted search (no per-query cost). Unconfigured or failed
    returns [], never a fabricated result."""
    try:
        _, results = web_search.search(query, max_results, exclude=_PAID)
    except web_search.SearchFailed:
        return []
    return [r.as_dict() for r in results]


def _run_search(conn, tenant_id: str, query: str, max_results: int) -> List[dict]:
    results = _search_paid(conn, query, max_results)
    if results is not None:
        return results  # includes a real "no results" answer - no need to also search again
    return _search_free(query, max_results)


def build_web_fallback_context(
    conn, tenant_id: str, query_text: str, max_results: int = _MAX_RESULTS,
) -> Tuple[str, List[dict]]:
    """
    The real, confidence-gated last resort - see this module's own
    docstring for the full, layered gate. Returns ("", []) (never a
    placeholder, never a fabricated citation) whenever any layer of the
    gate fails: the question doesn't look answerable, search is
    unconfigured, the search itself fails, or fewer than
    MIN_SOURCES_REQUIRED distinct results come back.

    On success, returns (context_text, sources): context_text is a
    labeled, numbered block ("[External N] title - snippet (source:
    url)") ready to hand to generate_answer() as its own web_context
    section; sources is a list of {"url", "title"} dicts meant to be
    appended to the response's own `sources` list (see answer_query()'s
    own docstring for why a `url` key, absent from chunk-citation dicts,
    is how a caller tells the two apart).
    """
    if not looks_like_answerable_question(query_text):
        return "", []

    business = _load_tenant_business_context(conn, tenant_id)
    scoped_query = _build_scoped_query(query_text, business)

    try:
        results = _run_search(conn, tenant_id, scoped_query, max_results)
    except Exception as e:  # noqa: BLE001 - a search failure must degrade to "no fallback", never crash the chat turn
        logger.warning("RAG web fallback search failed for tenant=%s: %s", tenant_id, e)
        return "", []

    if len(results) < MIN_SOURCES_REQUIRED:
        return "", []

    lines = []
    sources = []
    for index, result in enumerate(results[:max_results], start=1):
        snippet = f" - {result['snippet']}" if result["snippet"] else ""
        lines.append(f"[External {index}] {result['title']}{snippet} (source: {result['url']})")
        sources.append({"url": result["url"], "title": result["title"]})
    return "\n".join(lines), sources
