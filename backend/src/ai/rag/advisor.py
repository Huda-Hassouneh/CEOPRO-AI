"""
KEEL's business advisor: one question in, one evidence-backed answer out.

The language model is never the database, the calculator or the source
of truth. Each question goes through the same steps:

1. understand - intents and specifics (understanding.py), carrying the
   previous turn's product, country, period, quantity and currency into a
   follow-up;
2. gather company evidence the member's role may see (access.py): live
   records for the intents asked about, analysis tools, product records,
   customer reviews, document passages and the product guide - each fact
   becoming one evidence item with a link to the screen it comes from;
3. research what the company's records cannot answer (research/), reading
   the actual source pages and preferring official sources for legal,
   tax and customs questions;
4. calculate with deterministic code (trade/landed_cost.py) - every input
   traced to the user, the company's records or a cited source;
5. draft: the model writes the answer as claims citing evidence ids;
6. verify every claim against its evidence (citations.py), with one
   repair round when something does not check out;
7. render numbered references for the interface.

Missing, not permitted, failed, unconfigured and stale evidence are each
reported as what they are - never as zero, and never as proof that
something does not exist.
"""
import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Dict, List, Optional

from src.ai.billing import credits
from src.ai.rag import access as acl
from src.ai.rag import business_analysis, citations, conversation_memory, evidence as ev, llm_client, product_guide
from src.ai.rag import business_records, understanding, untrusted
from src.ai.rag.periods import MONTH_NAMES, label_dates as periods_label
from src.ai.core.business_time import business_today
from src.ai.rag.business_tools import build_financial_facts_block
from src.ai.rag.orchestrator import build_tool_facts_blocks
from src.ai.rag.pipeline import DEFAULT_RERANK_CANDIDATES, run_retrieval
from src.ai.rag.structured_context import build_fact_sections
from src.ai.research import research as public_research
from src.ai.trade import landed_cost
from src.ai.trade import messages as trade_messages

logger = logging.getLogger("KEEL_ADVISOR")

MAX_TOKENS = int(os.getenv("ADVISOR_MAX_TOKENS", "1500"))
# A compact prompt, for providers whose per-request ceiling (e.g. a free
# tier's tokens per minute) the full one exceeds.
# Earlier turns sent with a question (user + assistant messages) and evidence records sent when the
# question names no business need: more costs tokens on every call without improving the answer.
HISTORY_MESSAGES = int(os.getenv("ADVISOR_HISTORY_MESSAGES", "6"))
GENERAL_ITEMS = int(os.getenv("ADVISOR_GENERAL_ITEMS", "12"))
COMPACT_ITEMS, COMPACT_EXCERPT_CHARS, COMPACT_MAX_TOKENS = 24, 350, 1100
U = understanding

# Which live fact sections (structured_context.py) each intent needs.
_SECTIONS_FOR_INTENT = {
    U.SALES: ("sales", "insights"), U.FINANCIALS: ("sales", "insights"), U.PRODUCTS: ("sales", "price_gaps"),
    U.PRICING: ("price_gaps", "price_ladder", "sales"), U.INVENTORY: ("forecasts",), U.FORECAST: ("forecasts",),
    U.COMPETITORS: ("competitors", "price_gaps", "price_ladder", "competitor_activity"), U.REVIEWS: ("sentiment",),
    U.CUSTOMER_PREFERENCE: ("sentiment", "competitors"), U.MARKET_RESEARCH: ("competitors", "sales"),
    U.ADVICE: ("sales", "insights", "price_gaps", "price_ladder", "forecasts", "sentiment"),
}
_PRIVATE_ONLY = frozenset({U.SALES, U.FINANCIALS, U.INVENTORY, U.FORECAST, U.MARKETING, U.DOCUMENTS, U.PRODUCTS,
                           U.PRICING, U.COMPANY})
# Why public research did not run, in words the model can pass on.
_RESEARCH_FAILED = {
    public_research.NOT_CONFIGURED: "web search is not set up on this server - an administrator needs to add a "
                                    "search provider key",
    public_research.SEARCH_FAILED: "the web search service failed",
    public_research.BUDGET_EXHAUSTED: "today's web search allowance is used up",
}
_CAPABILITY_FOR_INTENT = {
    U.SALES: (acl.SALES,), U.FINANCIALS: (acl.SALES, acl.COSTS), U.INVENTORY: (acl.INVENTORY,),
    U.FORECAST: (acl.FORECASTS,), U.MARKETING: (acl.MARKETING,), U.COMPETITORS: (acl.COMPETITORS,),
    U.REVIEWS: (acl.REVIEWS,), U.DOCUMENTS: (acl.DOCUMENTS,), U.PRICING: (acl.CATALOG,), U.PRODUCTS: (acl.CATALOG,),
}
# Analysis blocks (orchestrator.py, business_analysis.py, business_tools.py) by
# their opening words: who may see each one and where it lives in the app.
_TOOL_BLOCKS = (
    ("Top-selling products by gross profit", (acl.SALES, acl.COSTS), "/products"),
    ("Products at or below their reorder level", (acl.INVENTORY,), "/demand/inventory"),
    ("Inventory (source", (acl.INVENTORY,), "/demand/inventory"),
    ("Tracked competitors", (acl.COMPETITORS,), "/market/competitors"),
    ("Competitors (source", (acl.COMPETITORS,), "/market/competitors"),
    ("Demand forecast summary", (acl.FORECASTS,), "/demand"),
    ("Recent marketing campaigns", (acl.MARKETING,), "/marketing"),
    ("Marketing campaigns", (acl.MARKETING,), "/marketing"),
    ("Root-cause signals", (acl.SALES, acl.COSTS), "/sales"),
    ("Product sales trends", (acl.SALES,), "/sales"),
    ("Restock check", (acl.INVENTORY, acl.FORECASTS), "/demand/inventory"),
    ("Competitor comparison", (acl.COMPETITORS, acl.CATALOG), "/market/competitors"),
    ("Gross margin analysis", (acl.SALES, acl.COSTS), "/sales"),
    ("Per-unit margin from the product catalog", (acl.CATALOG, acl.COSTS), "/products"),
)
_LEADS = {
    "evidence_mode": {
        "en": "The assistant's writing service is unavailable right now, so here is the evidence KEEL found for "
              "your question, unsummarised:",
        "ar": "خدمة كتابة الإجابات غير متاحة الآن، لذلك هذه الأدلة التي وجدها KEEL لسؤالك كما هي دون تلخيص:",
    },
    "allowance_used": {
        "en": "Your plan's AI allowance for this period is used up, so here is the evidence KEEL found for your "
              "question, unsummarised:",
        "ar": "تم استهلاك رصيد الذكاء الاصطناعي في باقتك لهذه الفترة، لذلك هذه الأدلة التي وجدها KEEL لسؤالك كما هي "
              "دون تلخيص:",
    },
    "unverifiable": {
        "en": "I couldn't put together an answer that the evidence fully supports, so here is what KEEL found for "
              "your question instead:",
        "ar": "لم أتمكن من صياغة إجابة تدعمها الأدلة بالكامل، لذلك هذا ما وجده KEEL لسؤالك:",
    },
    "unlinked": {
        "en": "KEEL could not link this answer to its evidence, so treat it as unverified.",
        "ar": "لم يتمكن KEEL من ربط هذه الإجابة بأدلتها، لذا اعتبرها غير مؤكدة.",
    },
}
# What KEEL itself writes into evidence titles, notes and limitations.
_WORDS = {
    "your_message": ("Your message", "رسالتك"),
    "earlier_message": ("Your earlier message", "رسالتك السابقة"),
    "message_part": ("Your message (relevant part)", "رسالتك (الجزء المتعلق بالسؤال)"),
    "summary_title": ("KEEL summary: {name}", "ملخص KEEL: {name}"),
    "summary_limit": ("a generated summary; the live records are the exact figures",
                      "ملخص مُولّد؛ الأرقام الدقيقة في السجلات الحية"),
    "product_title": ("Product: {name}", "المنتج: {name}"),
    "catalogue_title": ("Your product catalogue", "كتالوج منتجاتك"),
    "catalogue_line": ("You have {count} products: {items}{more}.", "لديك {count} منتجاً: {items}{more}."),
    "catalogue_more": (" (and {rest} more)", " (و{rest} أخرى)"),
    "same_source": ("(same source as above)", "(المصدر نفسه أعلاه)"),
    "selling_price": ("selling price {value} {currency}", "سعر البيع {value} {currency}"),
    "cost_price": ("recorded cost price {value} {currency}", "سعر التكلفة المسجّل {value} {currency}"),
    "reviews_title": ("Customer reviews: overview", "تقييمات الزبائن: نظرة عامة"),
    "reviews_count": ("{count} stored customer reviews", "{count} تقييماً محفوظاً للزبائن"),
    "reviews_rating": ("; average rating {rating} out of 5 from {rated} rated reviews",
                       "؛ متوسط التقييم {rating} من 5 من {rated} تقييماً"),
    "reviews_span": ("{summary}, from {first} to {last}.", "{summary}، من {first} إلى {last}."),
    "review_title": ("Customer review", "تقييم زبون"),
    "review_about": ("Customer review about {product}", "تقييم زبون عن {product}"),
    "review_limit": ("one customer's own words, not a measure of all customers",
                     "كلام زبون واحد، وليس مقياساً لكل الزبائن"),
    "stated": ("stated in your message", "حسب رسالتك"),
    "stated_quantity": ("{value} {unit} stated in your message", "{value} {unit} حسب رسالتك"),
    "stated_rate": ("exchange rate stated in your message", "سعر الصرف حسب رسالتك"),
    "cited": ("from a cited source", "من مصدر مذكور"),
    "your_cost": ("your recorded cost price for this product", "سعر التكلفة المسجّل لديك لهذا المنتج"),
    "your_price": ("your current selling price", "سعر البيع الحالي لديك"),
    "calc_comparison": ("Landed cost comparison", "مقارنة التكلفة الواصلة"),
    "calc_title": ("Landed cost calculation", "حساب التكلفة الواصلة"),
    "calc_line": ("Imported: {per_unit} {currency} per unit ({total} total); local: {local} per unit ({local_total} "
                  "total); difference {saving} {currency} ({pct}% of the local cost); cheaper: {cheaper}.",
                  "المستورد: {per_unit} {currency} للوحدة ({total} إجمالاً)؛ المحلي: {local} للوحدة ({local_total} "
                  "إجمالاً)؛ الفرق {saving} {currency} ({pct}% من التكلفة المحلية)؛ الأرخص: {cheaper}."),
    "cheaper_import": ("importing", "الاستيراد"), "cheaper_local": ("buying locally", "الشراء المحلي"),
    "cheaper_equal": ("neither", "لا فرق"),
    "break_even": ("Break-even order size: {quantity} units ({note}).", "كمية التعادل: {quantity} وحدة ({note})."),
    "break_even_none": ("Break-even: {note}.", "التعادل: {note}."),
    "scenario": ("Scenario '{label}': {per_unit} per unit", "سيناريو «{label}»: {per_unit} للوحدة"),
    "scenario_saving": (", difference {saving}", "، الفرق {saving}"),
    "still_needed": ("Inputs still needed: {items}.", "مدخلات ما زالت مطلوبة: {items}."),
    "assumption": ("Assumption: {text}", "افتراض: {text}"),
    "not_included": ("Not included: {text}", "غير مشمول: {text}"),
    "nothing_yet": ("No figures could be calculated yet.", "لم يُحسب أي رقم بعد."),
}


def _w(key: str, language: str, **values) -> str:
    english, arabic = _WORDS[key]
    return (arabic if language == "ar" else english).format(**values)


_STOP_WORDS = {"the", "and", "for", "with", "what", "how", "why", "are", "is", "my", "our", "your", "this", "that",
               "of", "to", "in", "on", "a", "an", "do", "does", "can", "should", "about", "me", "we", "i",
               # Question and helper words match any sentence that happens to use them ("Who won ..." matched
               # "customers who aren't happy"), so they never count as a shared topic.
               "who", "whom", "whose", "which", "when", "where", "was", "were", "did", "has", "have", "had",
               "been", "will", "would", "could", "you", "they", "their", "them", "its", "from", "there", "than",
               "then", "متى", "أين", "وين", "مين", "ايش", "هذا", "هذه", "كان", "كانت",
               "ما", "ماذا", "كيف", "لماذا", "هل", "في", "من", "على", "عن", "الى", "إلى", "شو", "ليش", "قديش",
               "انا", "أنا",
               # Request verbs: "tell me about my company" is about the company, not about telling.
               "tell", "show", "give", "explain", "describe", "summarise", "summarize", "know", "please", "want",
               "need", "like", "find", "list", "see", "get", "let", "اعطني", "عطيني", "خبرني", "قلي", "قل", "اشرح",
               "وضح", "لخص", "اعرض", "اريد", "بدي", "ابغى", "عايز",
               # Period words say when, not what: "the last 3 months" matched "Last reviewed September".
               "last", "next", "past", "previous", "current", "month", "months", "year", "years", "week", "weeks",
               "days", "today", "much", "many", "اخر", "الماضي", "القادم", "الشهر", "شهر", "السنه", "سنه", "الاسبوع",
               # Ranking words say how to order, not what about: "top 5 customers" is about customers.
               "top", "best", "most", "highest", "biggest", "largest", "lowest", "افضل", "اكثر", "اعلى", "اكبر"}
# Compared after the same normalisation as the text (أ -> ا, ى -> ي), or the Arabic ones never match.
_STOP = {understanding._norm(w) for w in _STOP_WORDS}


def _language(question: str) -> str:
    return product_guide.question_language(question)


def _company(conn, tenant_id: str) -> dict:
    if conn is None:
        return {}
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT business_name, business_type, country_code, primary_currency, is_demo, city "
                "FROM companies WHERE tenant_id = %s;", (tenant_id,))
            row = cursor.fetchone()
    except Exception:  # noqa: BLE001 - answer without the profile rather than not at all
        conn.rollback()
        return {}
    if not row:
        return {}
    name, business_type, country, currency, is_demo, city = row
    return {"business_name": name, "business_type": business_type, "country_code": country, "currency": currency,
            "is_demo": bool(is_demo), "city": city}


def _catalog(conn, tenant_id: str, access: acl.Access) -> List[dict]:
    if conn is None or not access.allows(acl.CATALOG):
        return []
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT product_id, product_name->>'en', product_name->>'ar', localized_text(product_name),
                   current_price, cost_price, currency
            FROM products WHERE tenant_id = %s AND deleted_at IS NULL
            ORDER BY updated_at DESC NULLS LAST LIMIT 3000;
            """,
            (tenant_id,),
        )
        rows = cursor.fetchall()
    out = []
    for product_id, en, ar, any_name, price, cost, currency in rows:
        name = en or any_name or ar
        out.append({"product_id": str(product_id), "name": name, "name_alt": ar if ar and ar != name else None,
                    "price": price, "cost": cost, "currency": currency})
    return out


def _top_product(conn, tenant_id: str, catalog: List[dict], access: acl.Access) -> Optional[dict]:
    """The product with the most sales revenue in the last 90 days ("my top
    product"), when the member may see sales; None when there are no sales."""
    if conn is None or not catalog or not access.allows(acl.SALES, acl.CATALOG):
        return None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT ii.product_id FROM invoice_items ii
                JOIN invoices i ON i.tenant_id = ii.tenant_id AND i.invoice_id = ii.invoice_id
                WHERE ii.tenant_id = %s AND ii.product_id IS NOT NULL
                  AND i.issue_date >= CURRENT_DATE - INTERVAL '90 days'
                GROUP BY ii.product_id ORDER BY SUM(ii.total_price) DESC LIMIT 1;
                """,
                (tenant_id,),
            )
            row = cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - the question is still answered, just without the product named
        logger.info("top product lookup failed: %s", type(exc).__name__)
        conn.rollback()
        return None
    by_id = {p["product_id"]: p for p in catalog}
    return by_id.get(str(row[0])) if row else None


_ARABIC_PUNCTUATION = re.compile("[\u060c\u061b\u061f\u066a-\u066d\u06d4]")


# Month names and years say when, not what: every document footer "Last reviewed September 2026" would
# otherwise match every question about September's sales.
_DATE_WORDS = {understanding._norm(name) for names in MONTH_NAMES.values() for name in names if " " not in name}


def _content_words(text: str) -> set:
    # Arabic punctuation sits inside the Arabic letter range: "طلب؟" must still be the word "طلب".
    words = re.findall(r"[\w؀-ۿ]{3,}", _ARABIC_PUNCTUATION.sub(" ", understanding._norm(text)))
    return {w[2:] if w.startswith("ال") and len(w) > 4 else w for w in words
            if w not in _STOP and w not in _DATE_WORDS and not w.isdigit()}


def _relevant(question: str, text: str) -> bool:
    wanted = _content_words(question)
    if not wanted:
        return False
    found = wanted & _content_words(text)
    return len(found) >= min(2, len(wanted))


# Retrieval always returns its nearest chunks, so each must also pass a
# relevance check before it becomes evidence. Shared words alone (_relevant)
# would drop every match semantic search makes across languages - an Arabic
# question about an English document shares none - so a chunk also counts
# when it is the retrieved chunk closest in meaning to the question (or
# within SEMANTIC_MARGIN of it) and at least SEMANTIC_MIN_SIMILARITY close.
# Relative, not a fixed cut-off: the static model's similarities are low and
# vary by question (right document 0.18-0.39, a wrong one up to 0.30, in
# scripts/rag_runtime_check.py's measurements), so no single cut-off fits.
SEMANTIC_MIN_SIMILARITY = float(os.getenv("RAG_SEMANTIC_MIN_SIMILARITY", "0.15"))
SEMANTIC_MARGIN = float(os.getenv("RAG_SEMANTIC_MARGIN", "0.05"))


def _semantic_check(question: str, texts: List[str]) -> Optional[Callable[[str], bool]]:
    """text -> close enough to `question` by meaning, among `texts` (the
    retrieved chunks); None without an embedding model."""
    from src.ai.rag.embeddings import try_embed

    vectors = try_embed([question] + list(texts)) if texts else None
    if vectors is None:
        return None
    similarity = {text: float(vector @ vectors[0]) for text, vector in zip(texts, vectors[1:])}
    best = max(similarity.values())

    def close(text: str) -> bool:
        score = similarity.get(text)
        return score is not None and score >= SEMANTIC_MIN_SIMILARITY and score >= best - SEMANTIC_MARGIN

    return close


def _chunk_filter(question: str, texts: List[str]) -> Callable[[str], bool]:
    """text -> does this retrieved chunk answer `question`: it shares its words, or is the closest in meaning.
    Closeness is measured against every retrieved chunk, the word-matched ones included - against the leftovers
    alone the best of them always passed (a supplier agreement shown for a leave question)."""
    close = _semantic_check(question, texts) if any(not _relevant(question, t) for t in texts) else None
    return lambda text: _relevant(question, text) or (close is not None and close(text))


def _status(statuses: List[dict], need: str, status: str, detail: str = "") -> None:
    statuses.append({"need": need, "status": status, **({"detail": detail} if detail else {})})


# --- gathering ---------------------------------------------------------------

def _user_inputs(registry: ev.EvidenceRegistry, question: str, previous: Optional[dict], follow_up: bool,
                 language: str) -> Dict[str, str]:
    """The user's own messages as citable evidence (values they stated)."""
    ids = {}
    if follow_up and previous and previous.get("question") and re.search(r"\d|https?://", previous["question"]):
        ids["previous"] = registry.add(ev.USER_INPUT, _w("earlier_message", language), previous["question"], ev.USER,
                                       ev.USER_PROVIDED).id
    if re.search(r"\d|https?://", understanding._norm(question)):
        ids["current"] = registry.add(ev.USER_INPUT, _w("your_message", language), question, ev.USER,
                                      ev.USER_PROVIDED).id
    return ids


def _split_history(history: Optional[list]) -> tuple:
    """(recent, older, recent_full): the newest HISTORY_MESSAGES turns, sent
    to the model as turns (a long one reduced to its start and end);
    everything before them, recalled by _recall() instead; and the newest
    turns in full, so _recall() can find the middle of a long one."""
    history = [m for m in (history or []) if isinstance(m, dict) and isinstance(m.get("content"), str)]
    cut = max(0, len(history) - HISTORY_MESSAGES)
    recent = [{**m, "content": conversation_memory.focus(m["content"])} for m in history[cut:]]
    return recent, history[:cut], history[cut:]


def _recall(registry: ev.EvidenceRegistry, question: str, full_question: str, older: list, recent_full: list,
            language: str) -> int:
    """The parts of what the user wrote that the model would not otherwise
    see - older messages, and the middle of long ones - that bear on
    `question`, added as their own evidence (conversation_memory.py)."""
    sources = [(_w("earlier_message", language), m["content"]) for m in older if m.get("role") == "user"]
    sources += [(_w("earlier_message", language), m["content"]) for m in recent_full
                if m.get("role") == "user" and conversation_memory.is_long(m["content"])]
    if conversation_memory.is_long(full_question):
        sources.append((_w("message_part", language), full_question))
    passages = conversation_memory.relevant_passages(sources, question)
    for label, text in passages:
        registry.add(ev.USER_INPUT, label, text, ev.USER, ev.USER_PROVIDED)
    return len(passages)


# The intents each generated data summary (structured_summaries.py) speaks to. One about another topic only
# shares incidental words with the question ("as more sales come in" in the forecast summary) and takes the
# place of evidence that answers it; the live records are the exact figures anyway.
_SUMMARY_TOPICS = {
    "sales_history": {U.SALES, U.FINANCIALS, U.PRODUCTS, U.ADVICE},
    "demand_forecast": {U.FORECAST, U.INVENTORY, U.ADVICE},
    "market_pricing": {U.PRICING, U.COMPETITORS, U.MARKET_RESEARCH, U.ADVICE},
    "competitor_landscape": {U.COMPETITORS, U.MARKET_RESEARCH, U.CUSTOMER_PREFERENCE},
    "sentiment_trends": {U.REVIEWS, U.CUSTOMER_PREFERENCE},
    "strategic_insights": {U.ADVICE, U.PRICING, U.FINANCIALS},
}


def _summary_off_topic(path: Optional[str], intents) -> bool:
    if not intents or not (path or "").startswith("_generated/"):
        return False
    topics = _SUMMARY_TOPICS.get(path[len("_generated/"):].rsplit(".", 1)[0])
    return topics is not None and not topics & set(intents)


# Generated summaries that exact records for the question replace (fact-section key -> summary slot).
_SUPERSEDED_SUMMARIES = {"sales": "sales_history", "forecasts": "demand_forecast"}


def _summary_superseded(path: Optional[str], superseded) -> bool:
    slot = (path or "")[len("_generated/"):].rsplit(".", 1)[0] if (path or "").startswith("_generated/") else None
    return slot is not None and slot in {_SUPERSEDED_SUMMARIES.get(key) for key in superseded}


def _documents(conn, tenant_id: str, question: str, access: acl.Access, registry: ev.EvidenceRegistry,
               top_k: int, statuses: List[dict], language: str = "en", intents=(), superseded=frozenset()) -> int:
    if conn is None:
        return 0
    try:
        context = run_retrieval(conn, tenant_id, question, top_k=DEFAULT_RERANK_CANDIDATES)
    except Exception as exc:  # noqa: BLE001 - the rest of the evidence still answers
        logger.warning("document retrieval failed (tenant=%s): %s", tenant_id, exc)
        conn.rollback()
        _status(statuses, "company_documents", "failed", "document search was unavailable")
        return 0
    if not context.sources:
        return 0
    chunk_ids = [source["chunk_id"] for source in context.sources]
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.chunk_id, c.chunk_index, c.chunk_text_content, c.page_number, m.document_id, m.file_name,
                   m.storage_bucket_path, m.uploaded_at
            FROM rag_document_chunks c
            JOIN rag_documents_metadata m ON m.tenant_id = c.tenant_id AND m.document_id = c.document_id
            WHERE c.tenant_id = %s AND c.chunk_id = ANY(%s::uuid[]);
            """,
            (tenant_id, chunk_ids),
        )
        rows = {str(row[0]): row for row in cursor.fetchall()}
    added, withheld = 0, 0
    admits = _chunk_filter(question, [row[2] for row in rows.values()])
    for source in context.sources:
        row = rows.get(source["chunk_id"])
        if row is None:
            continue
        _chunk_id, index, text, page, document_id, file_name, path, uploaded_at = row
        needed = acl.document_capabilities(path)
        if not access.allows(*needed):
            withheld += 1
            continue
        if added >= top_k:
            continue
        if _summary_off_topic(path, intents) or _summary_superseded(path, superseded) or not admits(text):
            continue
        summary = (path or "").startswith("_generated/")
        title = (_w("summary_title", language, name=file_name.rsplit('.', 1)[0].replace('_', ' ')) if summary
                 else file_name)
        registry.add(ev.COMPANY_SUMMARY if summary else ev.COMPANY_DOCUMENT, title, text, ev.COMPANY,
                     ev.SUMMARISED if summary else ev.OBSERVED, route="/ai-advisor",
                     locator=f"page {page}" if page else f"passage {index + 1}", observed_at=uploaded_at,
                     capabilities=needed,
                     limitations=[_w("summary_limit", language)] if summary else [])
        added += 1
    if withheld and not added:
        _status(statuses, "company_documents", "not_permitted", "matching documents exist but your role can't open them")
    return added


def _fact_sections(conn, tenant_id: str, u: understanding.Understanding, access: acl.Access,
                   registry: ev.EvidenceRegistry, statuses: List[dict], skip: frozenset = frozenset()) -> int:
    """The live snapshot sections the question's intents need; `skip` names the
    ones _records() already answered exactly for the asked period."""
    if conn is None:
        return 0
    wanted = set()
    for intent in u.intents:
        wanted.update(_SECTIONS_FOR_INTENT.get(intent, ()))
    general = not u.intents
    if not wanted and not general:
        return 0
    sections = build_fact_sections(conn, tenant_id, allowed=access.allows)
    added = 0
    for section in sections:
        if section.key in skip or (not general and section.key not in wanted):
            continue
        added += len(registry.add_fact_lines(section.lines, route=section.route, capabilities=section.capabilities,
                                             observed_at=datetime.now(timezone.utc)))
    return added


def _analysis(conn, tenant_id: str, u: understanding.Understanding, access: acl.Access,
              registry: ev.EvidenceRegistry, exact_sales: bool = False) -> int:
    if conn is None:
        return 0
    question = u.effective_question
    blocks = list(business_analysis.build_analysis_blocks(conn, tenant_id, question, _language(u.question)))
    superseded = business_analysis.superseded_prefixes(blocks)
    blocks += [(label, text) for label, text in build_tool_facts_blocks(conn, tenant_id, question)
               if label != "CEOPRO_APPLICATION_KNOWLEDGE" and not text.startswith(superseded)]
    # The trailing-window margin block would contradict the asked calendar period; _records() gives its
    # gross profit instead.
    if access.allows(acl.SALES, acl.COSTS) and (U.FINANCIALS in u.intents or U.SALES in u.intents) and not (
            exact_sales and u.slots.get("periods")):
        financial = build_financial_facts_block(conn, tenant_id, question, window_days=u.slots.get("period_days"))
        if financial:
            blocks.append(("TENANT_BUSINESS_DATA", financial))
    added = 0
    for _label, text in blocks:
        rule = next((r for r in _TOOL_BLOCKS if text.startswith(r[0])), None)
        capabilities, route = (frozenset(rule[1]), rule[2]) if rule else (acl.ALL_CAPABILITIES, None)
        if not access.allows(*capabilities):
            continue
        added += len(registry.add_fact_lines(text.splitlines(), route=route, capabilities=capabilities,
                                             observed_at=datetime.now(timezone.utc)))
    return added


def _sales_periods(u: understanding.Understanding, today) -> List[dict]:
    """The periods to report sales for: those the question names, else its rolling window, else the last 30 days."""
    if u.slots.get("periods"):
        return list(u.slots["periods"])
    days = int(u.slots.get("period_days") or 30)
    start = today - timedelta(days=days - 1)
    return [{"start": start.isoformat(), "end": (today + timedelta(days=1)).isoformat(),
             "label": f"the last {days} days", "kind": "days"}]


_NAMED_RECORD_TITLES = ("Stock of ", "Demand forecast for ", "Sales of the products asked about")
_HEADLINE_TITLES = ("Sales for ",)
_RANKING = re.compile(r"(?<![a-z])(top|best|worst|most|least|rank|ranking|which products?|what sold|bestsell)|"
                      r"اكثر|افضل|اقل|اسوا|ترتيب|اي منتج|شو المنتج")  # a period's own total, the first thing an answer about it says


def _records(conn, tenant_id: str, u: understanding.Understanding, access: acl.Access,
             registry: ev.EvidenceRegistry, statuses: List[dict], language: str = "en", today=None) -> tuple:
    """Exact records for the periods and products the question names (business_records.py).
    Returns (items added, fact-section keys these records replace)."""
    if conn is None:
        return 0, frozenset()
    intents = set(u.intents)
    slots = u.slots
    product_ids = [p["product_id"] for p in slots.get("products") or []]
    now = datetime.now(timezone.utc)
    added, replaced = 0, set()

    def add(lines: List[str], route: str, *capabilities: str) -> None:
        nonlocal added
        if not lines:
            return
        items = registry.add_fact_lines(lines, route=route, capabilities=frozenset(capabilities), observed_at=now)
        for item in items:
            # Computed for exactly this question; the named products' own lines most of all (_evidence_mode).
            # A word, not a number: numbers in `data` count as evidence for the citation check.
            named = item.title.startswith(_NAMED_RECORD_TITLES) or " asked about" in item.title
            headline = item.title.startswith(_HEADLINE_TITLES) and item.excerpt.startswith(("Revenue ", "- Revenue"))
            item.data = {**(item.data or {}), "exact": "named" if named else "headline" if headline or
                         item.title.startswith("Comparison of the periods") else "record"}
        added += len(items)

    def guarded(need: str, detail: str, build: Callable[[], None]) -> bool:
        """A failed query is reported as failed (never as "no data") and the rest still answers."""
        try:
            build()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s failed (tenant=%s): %s", need, tenant_id, exc)
            rollback = getattr(conn, "rollback", None)
            if rollback:
                rollback()
            _status(statuses, need, "failed", detail)
            return False

    day = today or business_today(conn)
    # A ranking question ("top 10", "which sold least") gets the longer lists; any other gets the top 5.
    ranking = bool(slots.get("top_product")) or bool(_RANKING.search(understanding._norm(u.effective_question)))
    asks_sales = bool(intents & {U.SALES, U.FINANCIALS}) or slots.get("customer_ranking") or slots.get("top_product") \
        or (bool(slots.get("periods")) and bool(intents & {U.PRODUCTS, U.ADVICE, U.PRICING}) and not intents & {
            U.REVIEWS, U.FORECAST, U.INVENTORY, U.MARKET_RESEARCH, U.COMPETITORS, U.PRODUCT_RESEARCH})
    if asks_sales and access.allows(acl.SALES):
        def sales() -> None:
            coverage = business_records.sales_coverage(conn, tenant_id)
            periods = _sales_periods(u, day)
            several = len(periods) > 1
            for period in periods:
                add(business_records.sales_lines(
                    conn, tenant_id, period, product_ids=product_ids, language=language,
                    with_costs=access.allows(acl.COSTS) and (U.FINANCIALS in intents or not several),
                    series=bool(slots.get("series")), customers=bool(slots.get("customer_ranking")),
                    coverage=coverage, compare_previous=not several,
                    top=business_records.TOP_PRODUCTS if ranking and not several else 5), "/sales", acl.SALES)
            add(business_records.comparison_lines(conn, tenant_id, periods), "/sales", acl.SALES)

        if guarded("sales_records", "the sales figures for this period could not be read", sales):
            replaced.add("sales")

    if product_ids and intents & {U.INVENTORY, U.FORECAST, U.PRODUCTS}:
        stock = access.allows(acl.INVENTORY) and (U.INVENTORY in intents or U.PRODUCTS in intents)
        forecast = access.allows(acl.FORECASTS) and (U.FORECAST in intents or U.INVENTORY in intents)
        if stock:
            guarded("stock_records", "the stock levels could not be read", lambda: add(
                business_records.product_status_lines(conn, tenant_id, product_ids, language, with_stock=True,
                                                      with_forecast=False, with_sales=access.allows(acl.SALES)),
                "/demand/inventory", acl.INVENTORY))
        if forecast:
            both = access.allows(acl.INVENTORY)
            if guarded("forecast_records", "the demand forecasts could not be read", lambda: add(
                    business_records.product_status_lines(conn, tenant_id, product_ids, language, with_stock=False,
                                                          with_forecast=True, compare_stock=both), "/demand",
                    *((acl.FORECASTS, acl.INVENTORY) if both else (acl.FORECASTS,)))):
                replaced.add("forecasts")  # the named products' own forecasts, not every product's
    elif U.INVENTORY in intents and access.allows(acl.INVENTORY):
        guarded("stock_records", "the stock levels could not be read", lambda: add(
            business_records.stock_list_lines(conn, tenant_id, language, with_sales=access.allows(acl.SALES)),
            "/demand/inventory", acl.INVENTORY))

    if intents & {U.REVIEWS, U.CUSTOMER_PREFERENCE} and access.allows(acl.REVIEWS):
        asked = _sales_periods(u, day) if (slots.get("periods") or slots.get("period_days")) else []
        guarded("review_records", "the review counts could not be read", lambda: add(
            business_records.review_trend_lines(conn, tenant_id, asked, product_ids), "/market", acl.REVIEWS))

    if U.COMPANY in intents:
        guarded("company_profile", "the company profile could not be read", lambda: add(
            business_records.company_profile_lines(conn, tenant_id, with_competitors=access.allows(acl.COMPETITORS)),
            "/settings/company"))
    return added, frozenset(replaced)


CATALOGUE_NAMES = 40


def _catalogue_record(u: understanding.Understanding, catalog: List[dict], access: acl.Access,
                      registry: ev.EvidenceRegistry, language: str = "en") -> int:
    """The catalogue itself - how many products, and which - so that "how many
    products do I have" is answered from the records and not guessed."""
    if not catalog or U.PRODUCTS not in u.intents:
        return 0
    shown = catalog[:CATALOGUE_NAMES]
    items = "; ".join(
        p["name"] + (f" {p['price']} {p['currency']}" if p["price"] is not None else "") for p in shown)
    more = _w("catalogue_more", language, rest=len(catalog) - len(shown)) if len(catalog) > len(shown) else ""
    record = registry.add(ev.COMPANY_RECORD, _w("catalogue_title", language),
                          _w("catalogue_line", language, count=len(catalog), items=items, more=more),
                          ev.COMPANY, ev.OBSERVED, route="/products", capabilities=frozenset({acl.CATALOG}),
                          observed_at=datetime.now(timezone.utc))
    record.data = {**(record.data or {}), "exact": "headline"}
    return 1


def _product_records(u: understanding.Understanding, catalog: List[dict], access: acl.Access,
                     registry: ev.EvidenceRegistry, language: str = "en") -> Dict[str, dict]:
    """The named products' own records: selling price, and cost price when the role may see costs."""
    out = {}
    by_id = {p["product_id"]: p for p in catalog}
    for named in u.slots.get("products") or []:
        if u.public_scope and named.get("partial"):
            continue  # "the average price of olive oil in Jordan" is not about their olive oil's records
        product = by_id.get(named["product_id"])
        if not product:
            continue
        parts = []
        if product["price"] is not None:
            parts.append(_w("selling_price", language, value=product["price"], currency=product["currency"]))
        if access.allows(acl.COSTS) and product["cost"] is not None:
            parts.append(_w("cost_price", language, value=product["cost"], currency=product["currency"]))
        if not parts:
            continue
        item = registry.add(ev.COMPANY_RECORD, _w("product_title", language, name=product["name"]),
                            f"{product['name']}: " + "; ".join(parts),
                            ev.COMPANY, ev.OBSERVED, route=f"/products/{product['product_id']}",
                            capabilities=frozenset({acl.CATALOG}), observed_at=datetime.now(timezone.utc))
        out[product["product_id"]] = {**product, "evidence_id": item.id,
                                      "cost_visible": access.allows(acl.COSTS) and product["cost"] is not None}
    return out


def _reviews(conn, tenant_id: str, u: understanding.Understanding, access: acl.Access,
             registry: ev.EvidenceRegistry, statuses: List[dict], language: str = "en") -> int:
    if conn is None or not ({U.REVIEWS, U.CUSTOMER_PREFERENCE} & set(u.intents)):
        return 0
    if not access.allows(acl.REVIEWS):
        _status(statuses, "customer_reviews", "not_permitted", "your role can't see customer reviews")
        return 0
    product_ids = [p["product_id"] for p in u.slots.get("products") or []]
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT r.review_text, r.review_rating, r.review_date, r.source_platform, r.subject_type,
                   localized_text(p.product_name)
            FROM reviews r LEFT JOIN products p ON p.tenant_id = r.tenant_id AND p.product_id = r.product_id
            WHERE r.tenant_id = %s AND r.safety_status = 'SAFE' AND r.subject_type IN ('BUSINESS', 'PRODUCT')
              AND (cardinality(%s::uuid[]) = 0 OR r.product_id = ANY(%s::uuid[]))
            ORDER BY r.review_date DESC LIMIT 400;
            """,
            (tenant_id, product_ids, product_ids),
        )
        rows = cursor.fetchall()
    if not rows:
        _status(statuses, "customer_reviews", "none_recorded", "no customer reviews are stored for this yet")
        return 0
    ratings = [float(r[1]) for r in rows if r[1] is not None]
    summary = _w("reviews_count", language, count=len(rows)) + (
        _w("reviews_rating", language, rating=f"{sum(ratings) / len(ratings):.1f}", rated=len(ratings)) if ratings else "")
    first, last = min(r[2] for r in rows).date(), max(r[2] for r in rows).date()
    registry.add(ev.COMPANY_RECORD, _w("reviews_title", language),
                 _w("reviews_span", language, summary=summary, first=first, last=last), ev.COMPANY,
                 ev.OBSERVED, route="/market", capabilities=frozenset({acl.REVIEWS}))
    from src.ai.rag.bm25_index import BM25Index

    # One example per distinct wording (customers repeat themselves; four copies of "fast delivery" say no more
    # than one), the closest matches to the question first, then the newest positive and negative ones so both
    # sides of opinion are shown.
    distinct = {}
    for i, row in enumerate(rows):
        distinct.setdefault(" ".join((row[0] or "").lower().split()), i)
    keep = sorted(distinct.values())
    index = BM25Index([(str(i), rows[i][0]) for i in keep])
    picked = [int(chunk.chunk_id) for chunk in index.query(u.effective_question, top_k=4)]
    for wanted in (lambda r: r is not None and float(r) >= 4, lambda r: r is not None and float(r) <= 2):
        picked += [i for i in keep if wanted(rows[i][1]) and i not in picked][:3]
    picked = picked or keep[:4]
    for i in picked:
        text, rating, date, platform, _subject, product = rows[i]
        title = _w("review_about", language, product=product) if product else _w("review_title", language)
        registry.add(ev.COMPANY_RECORD, title, text, ev.COMPANY, ev.OBSERVED, route="/market",
                     observed_at=date, locator=" · ".join(filter(None, [platform, f"{float(rating):.1f}/5" if rating is not None else None])),
                     capabilities=frozenset({acl.REVIEWS}),
                     limitations=[_w("review_limit", language)])
    return 1 + len(picked)


# --- calculation ---------------------------------------------------------------

_AMOUNT_ROLES = (
    ("local_unit_price", ("local", "distributor", "locally", "here", "wholesaler here", "محلي", "محليا", "الموزع",
                          "هون", "هنا", "السوق المحلي", "من السوق")),
    ("freight", ("freight", "shipping", "shipment", "container", "شحن", "الشحن")),
    ("insurance", ("insurance", "تامين", "التامين")),
    ("clearance", ("clearance", "broker", "customs agent", "تخليص", "مخلص")),
    ("selling_price", ("sell it", "sell for", "selling price", "retail", "ابيع", "ببيع", "سعر البيع")),
    ("supplier_unit_price", ("supplier", "factory", "per unit", "each", "unit price", "quote", "quotation", "مورد",
                             "المورد", "المصنع", "للقطعه", "للوحده", "عرض سعر")),
)
_RATE_ROLES = (
    ("duty_rate", ("duty", "tariff", "customs", "جمرك", "جمركي", "رسوم", "تعرفه")),
    ("excise_rate", ("excise", "انتقائي")),
    ("sales_tax_rate", ("vat", "sales tax", "gst", "tax", "ضريبه", "القيمه المضافه", "المبيعات")),
)


def _role(before: str, roles, after: str = "") -> Optional[str]:
    """What a stated figure is: the role word closest before it ("freight
    300 JOD"), else the first one right after it ("4.5 JOD locally")."""
    best, best_position = None, -1
    normalized = understanding._norm(before)
    for key, words in roles:
        for word in words:
            position = normalized.rfind(understanding._norm(word))
            if position > best_position:
                best, best_position = key, position
    if best:
        return best
    normalized = understanding._norm(after)
    first, first_position = None, len(normalized) + 1
    for key, words in roles:
        for word in words:
            position = normalized.find(understanding._norm(word))
            if 0 <= position < first_position:
                first, first_position = key, position
    return first


def _calculation_inputs(u: understanding.Understanding, user_ids: Dict[str, str], products: Dict[str, dict],
                        destination_currency: str, research_rates: Dict[str, dict],
                        language: str = "en") -> Dict[str, landed_cost.Input]:
    user_ref = user_ids.get("current") or user_ids.get("previous")
    inputs: Dict[str, landed_cost.Input] = {}
    for amount in u.slots.get("amounts") or []:
        key = _role(amount["context"], _AMOUNT_ROLES, amount.get("after", ""))
        if key is None:
            key = "supplier_unit_price" if amount["currency"] != destination_currency else None
        if key and key not in inputs:
            inputs[key] = landed_cost.Input(Decimal(amount["amount"]), landed_cost.USER, amount["currency"], user_ref,
                                            _w("stated", language))
    for rate in u.slots.get("percentages") or []:
        key = _role(rate["context"], _RATE_ROLES, rate.get("after", ""))
        if key and key not in inputs:
            inputs[key] = landed_cost.Input(Decimal(rate["value"]), landed_cost.USER, "percent", user_ref,
                                            _w("stated", language))
    quantity = u.slots.get("quantity")
    if quantity:
        inputs["quantity"] = landed_cost.Input(Decimal(quantity["value"]), landed_cost.USER, "units", user_ref,
                                               _w("stated_quantity", language, value=quantity["value"],
                                                  unit=quantity["unit"]))
    if u.slots.get("fx_rate"):
        inputs["fx_rate"] = landed_cost.Input(Decimal(u.slots["fx_rate"]), landed_cost.USER, "rate", user_ref,
                                              _w("stated_rate", language))
    for key, found in research_rates.items():
        if key not in inputs:
            inputs[key] = landed_cost.Input(Decimal(found["value"]), landed_cost.EVIDENCE, found.get("unit", "percent"),
                                            found["evidence_id"], found.get("note") or _w("cited", language))
    product = next(iter(products.values()), None)
    if product:
        if "local_unit_price" not in inputs and product.get("cost_visible") and product.get("cost") is not None:
            inputs["local_unit_price"] = landed_cost.Input(Decimal(str(product["cost"])), landed_cost.COMPANY,
                                                           product["currency"], product["evidence_id"],
                                                           _w("your_cost", language))
        if "selling_price" not in inputs and product.get("price") is not None:
            inputs["selling_price"] = landed_cost.Input(Decimal(str(product["price"])), landed_cost.COMPANY,
                                                        product["currency"], product["evidence_id"],
                                                        _w("your_price", language))
    return inputs


def _extract_rates(ask: Optional[Callable], registry: ev.EvidenceRegistry, found: List[ev.Evidence],
                   u: understanding.Understanding, destination_currency: str) -> Dict[str, dict]:
    """Rates stated by the researched sources (duty, VAT/sales tax, excise,
    exchange rate), each kept only if the number really is in the item it
    is attributed to."""
    if ask is None or not found:
        return {}
    supplier_currency = next((a["currency"] for a in u.slots.get("amounts") or []
                              if a["currency"] != destination_currency), None)
    try:
        answer = ask([
            {"role": "system", "content": (
                "From the evidence items, extract only values that an item states explicitly. Answer with only JSON "
                "{\"duty_rate\": {...}, \"sales_tax_rate\": {...}, \"excise_rate\": {...}, \"fx_rate\": {...}, "
                "\"valuation_basis\": {...}} where each present value is {\"value\": \"20\", \"evidence\": \"E5\", "
                "\"note\": \"what exactly the item says it applies to\"}; valuation_basis value is \"CIF\" or "
                "\"FOB\"; fx_rate is units of the destination currency per 1 unit of the supplier currency. Omit "
                "anything not stated. Never guess.")},
            {"role": "user", "content": json.dumps({
                "product": [p["name"] for p in u.slots.get("products") or []], "hs_code": u.slots.get("hs_code"),
                "origin": u.slots.get("origin_country"), "destination": u.slots.get("destination_country"),
                "supplier_currency": supplier_currency, "destination_currency": destination_currency,
                "evidence": [untrusted.neutralize(item.prompt_block()) for item in found[:10]],
            }, ensure_ascii=False)},
        ], temperature=0, max_tokens=700)
        payload = json.loads(re.search(r"\{.*\}", answer, re.S).group(0))
    except Exception as exc:  # noqa: BLE001 - the calculation then lists these as missing
        logger.info("rate extraction unavailable: %s", type(exc).__name__)
        return {}
    rates = {}
    for key in ("duty_rate", "sales_tax_rate", "excise_rate", "fx_rate", "valuation_basis"):
        value = payload.get(key)
        if not isinstance(value, dict) or not value.get("evidence"):
            continue
        item = registry.get(str(value["evidence"]).strip("[]"))
        if item is None or item.kind != ev.WEB_PAGE:
            continue
        if key == "valuation_basis":
            basis = str(value.get("value") or "").upper()
            if basis in ("CIF", "FOB") and basis in item.excerpt.upper():
                rates[key] = {"value": "1", "unit": basis, "evidence_id": item.id, "note": value.get("note", "")}
            continue
        number = landed_cost.to_decimal(value.get("value"))
        if number is None or not any(found_value == number for found_value, _ in citations.numbers_in(item.excerpt)):
            continue
        rates[key] = {"value": str(number), "unit": "rate" if key == "fx_rate" else "percent", "evidence_id": item.id,
                      "note": str(value.get("note") or "")[:200]}
    return rates


def _fmt(value: Decimal, unit: str) -> str:
    if unit == "percent":
        return f"{value.quantize(Decimal('0.01')):,}%"
    places = Decimal("0.001") if unit in ("JOD", "KWD", "BHD", "OMR", "IQD", "LYD", "TND") else Decimal("0.01")
    if unit in ("units", "rate", ""):
        return f"{value.normalize():f}"
    return f"{value.quantize(places):,} {unit}"


def _calculation(u: understanding.Understanding, registry: ev.EvidenceRegistry, user_ids: Dict[str, str],
                 products: Dict[str, dict], company: dict, research_rates: Dict[str, dict],
                 statuses: List[dict], language: str = "en") -> Optional[dict]:
    destination_currency = company.get("currency") or next(
        (a["currency"] for a in u.slots.get("amounts") or []
         if _role(a["context"], _AMOUNT_ROLES, a.get("after", "")) == "local_unit_price"),
        None) or "JOD"
    inputs = _calculation_inputs(u, user_ids, products, destination_currency, research_rates, language)
    basis = research_rates.get("valuation_basis")
    valuation = landed_cost.Input(Decimal("1"), landed_cost.EVIDENCE, basis["unit"], basis["evidence_id"]) if basis else None
    result = landed_cost.calculate(inputs, destination_currency, u.slots.get("incoterm"), valuation)
    result.sensitivity = landed_cost.sensitivity(inputs, destination_currency, u.slots.get("incoterm"), valuation)
    say = lambda text: trade_messages.translate(text, language)  # noqa: E731

    input_ids = {key: item.evidence_id for key, item in inputs.items() if item.evidence_id}
    step_ids: Dict[str, str] = {}
    for step in result.steps:
        label, formula = say(step.label), say(step.formula)
        parts = [f"{label} = {formula} = {_fmt(step.value, step.unit)}"]
        for key in step.inputs:
            if key in inputs:
                parts.append(f"{say(key.replace('_', ' ').capitalize())}: "
                             f"{_fmt(inputs[key].value, inputs[key].unit or destination_currency)} "
                             f"({inputs[key].note or inputs[key].source})")
        refs = [input_ids[k] for k in step.inputs if k in input_ids] + [step_ids[k] for k in step.inputs if k in step_ids]
        item = registry.add(ev.CALCULATION, label, "; ".join(parts), ev.CALCULATED, ev.CALCULATED_STATUS,
                            data={"formula": formula, "value": _fmt(step.value, step.unit),
                                  "input_evidence": list(dict.fromkeys(refs)),
                                  "inputs": {k: inputs[k].as_dict() for k in step.inputs if k in inputs}})
        step_ids[step.key] = item.id
    summary = trade_messages.localize(result.as_dict(), language)
    lines = []
    if summary["comparison"]:
        c = summary["comparison"]
        lines.append(_w("calc_line", language, per_unit=c["landed_per_unit"], currency=c["currency"],
                        total=c["landed_total"], local=c["local_unit_price"], local_total=c["local_total"],
                        saving=c["saving_total"], pct=c["saving_pct"], cheaper=_w(f"cheaper_{c['cheaper']}", language)))
        if c.get("break_even_quantity"):
            lines.append(_w("break_even", language, quantity=c["break_even_quantity"], note=c.get("break_even_note", "")))
        elif c.get("break_even_note"):
            lines.append(_w("break_even_none", language, note=c["break_even_note"]))
    for scenario in summary["sensitivity"]:
        lines.append(_w("scenario", language, label=scenario["label"], per_unit=scenario["landed_per_unit"])
                     + (_w("scenario_saving", language, saving=scenario["saving_total"]) if scenario.get("saving_total") else "")
                     + ".")
    if summary["missing"]:
        lines.append(_w("still_needed", language, items="; ".join(
            f"{say(m['key'].replace('_', ' ').capitalize())} - {m['why']}" for m in summary["missing"])))
    lines += [_w("assumption", language, text=a) for a in summary["assumptions"]]
    lines += [_w("not_included", language, text=e) for e in summary["exclusions"]]
    title = _w("calc_comparison" if summary["comparison"] else "calc_title", language)
    summary_item = registry.add(ev.CALCULATION, title, "\n".join(lines) or _w("nothing_yet", language), ev.CALCULATED,
                                ev.CALCULATED_STATUS,
                                data={"summary": summary, "input_evidence": list(dict.fromkeys(
                                    list(input_ids.values()) + list(step_ids.values())))})
    _status(statuses, "landed_cost_calculation", "complete" if result.complete else "missing_inputs",
            ", ".join(m["key"] for m in result.missing))
    return {"evidence_id": summary_item.id, **summary}


# --- drafting ----------------------------------------------------------------

def _history_messages(history: Optional[list]) -> list:
    messages = llm_client._sanitize_history(history)
    for message in messages:
        if message["role"] == "assistant":
            message["content"] = citations.plain_text(message["content"])
    return messages


def _prompt(question: str, u: understanding.Understanding, company: dict, access: acl.Access,
            registry: ev.EvidenceRegistry, statuses: List[dict], compact: bool = False) -> str:
    lines = []
    if company:
        lines.append(f"Company: {company.get('business_name') or '-'} ({company.get('business_type') or 'business'}), "
                     f"country {company.get('country_code') or '-'}, currency {company.get('currency') or '-'}.")
        if company.get("is_demo"):
            lines.append("This is a demonstration workspace: its records are sample data - say so when you use them.")
    hidden = sorted(acl.ALL_CAPABILITIES - access.capabilities)
    if hidden:
        lines.append(f"The member asking has the role '{access.role or 'unknown'}', which may not see: "
                     f"{', '.join(hidden)}. If the question needs those, say their role can't see that data.")
    details = {k: v for k, v in u.slots.items() if k not in ("amounts", "percentages")}
    lines.append(f"Understood: needs {', '.join(u.intents) or 'general'}; details {json.dumps(details, ensure_ascii=False)}"
                 + ("; this is a follow-up to the previous question" if u.follow_up else ""))
    if u.slots.get("periods"):
        asked = "; ".join(f"{p['label']} = {periods_label(p)}" for p in u.slots["periods"])
        lines.append(f"Periods asked about: {asked}. Answer with the records for exactly these dates. Never give a "
                     "figure from another period (the last 30 days, a generated summary) as if it were one of these; "
                     "if a period has no records, say so and give the dates the records do cover.")
    items = registry.items()
    if compact:
        order = {ev.CALCULATION: 0, ev.USER_INPUT: 1, ev.PRODUCT_GUIDE: 2, ev.COMPANY_RECORD: 3, ev.WEB_PAGE: 4,
                 ev.COMPANY_DOCUMENT: 5, ev.COMPANY_SUMMARY: 6}
        keep = {item.id for item in sorted(items, key=lambda i: (order.get(i.kind, 7), int(i.id[1:])))[:COMPACT_ITEMS]}
        items = [item for item in items if item.id in keep]
    elif not u.intents and len(items) > GENERAL_ITEMS:
        # No business need was recognised (small talk, an off-topic or hostile message): a few records
        # are enough to orient the answer; sending every section only costs tokens.
        keep = {item.id for item in items[:GENERAL_ITEMS]}
        items = [item for item in items if item.id in keep]
    limit = COMPACT_EXCERPT_CHARS if compact else None
    blocks, seen_titles = [], set()
    for item in items:
        # Records of one list repeat a long title: say it once, the model still sees which source each is.
        repeat = item.title in seen_titles and len(item.title) > 40
        seen_titles.add(item.title)
        text = item.prompt_block(limit, title=_w("same_source", _language(question)) if repeat else None)
        blocks.append(text if item.kind in (ev.COMPANY_RECORD, ev.CALCULATION, ev.PRODUCT_GUIDE)
                      else untrusted.neutralize(text))
    evidence_text = "\n\n".join(blocks)
    lines.append("Evidence:\n" + (evidence_text or "(none)"))
    if statuses:
        lines.append("Evidence status:\n" + "\n".join(
            f"- {s['need']}: {s['status']}" + (f" ({s['detail']})" if s.get("detail") else "") for s in statuses))
    failed = next((s for s in statuses if s["need"] == "public_research" and s["status"] in _RESEARCH_FAILED), None)
    if failed:
        lines.append(f"Public research could not run for this question ({_RESEARCH_FAILED[failed['status']]}). "
                     "Say that once, plainly, as the reason the public part is unanswered - never that the "
                     "information doesn't exist or that you simply have no information. Still give everything the "
                     "evidence does establish, and say what the user can provide instead.")
    lines.append(f"Question: {question}{llm_client._reply_language_hint(question)}")
    return "\n\n".join(lines)


def _messages(question: str, u: understanding.Understanding, company: dict, access: acl.Access,
              registry: ev.EvidenceRegistry, statuses: List[dict], history: Optional[list], compact: bool) -> list:
    turns = _history_messages(history)
    return [{"role": "system", "content": f"{llm_client.SYSTEM_PROMPT}\n\n{citations.DRAFT_CONTRACT}"},
            *(turns[-4:] if compact else turns[-HISTORY_MESSAGES:]),
            {"role": "user", "content": _prompt(question, u, company, access, registry, statuses, compact)}]


# Refusals by AI Credits that are about the server, not the company: the model
# has no confirmed price, or its provider is switched off / over its platform
# cap. The company did nothing wrong and has plenty of credits, so the question
# still gets its evidence (the same fallback as a provider outage) instead of a
# bare error. A company's own plan or credit limit (SUBSCRIPTION_INACTIVE,
# BUDGET_EXHAUSTED, ...) is deliberately not here: that refusal is the answer.
_SERVER_SIDE_REFUSALS = {"COST_NOT_CONFIGURED": llm_client.LLMNotConfiguredError,
                         "PROVIDER_DISABLED": llm_client.LLMError, "PROVIDER_CAP_REACHED": llm_client.LLMError}


@contextmanager
def _server_refusals_as_llm_errors():
    try:
        yield
    except credits.BudgetError as err:
        error_type = _SERVER_SIDE_REFUSALS.get(err.reason)
        if error_type is None:
            raise
        raise error_type(f"AI call refused by the server's billing setup: {err.reason} ({err.detail})") from err


def _guarded(ask):
    def call(*args, **kwargs):
        with _server_refusals_as_llm_errors():
            return ask(*args, **kwargs)
    return call


def _call(messages: list, usage: dict, max_tokens: int = MAX_TOKENS) -> str:
    text, call_usage = llm_client._chat_completion_with_usage(messages, max_tokens=max_tokens, json_mode=True,
                                                              temperature=0.1)
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        usage[key] = usage.get(key, 0) + int((call_usage or {}).get(key) or 0)
    return text


def _fallback_draft(text: str, registry: ev.EvidenceRegistry, language: str) -> citations.Draft:
    """A reply that ignored the format: kept only sentence by sentence, all
    marked unverified, and any sentence with a figure not found anywhere in
    the evidence dropped."""
    pool = citations._evidence_numbers(registry.items())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?؟])\s+", llm_client.clean_answer_text(text or "")) if s.strip()]
    claims = [citations.Claim(text=_LEADS["unlinked"][language], kind=citations.GENERAL, evidence=[])]
    for sentence in sentences[:12]:
        numbers = [v for v, p in citations.numbers_in(sentence) if not (p == 0 and v <= 3)]
        if numbers and not all(any(citations._rounds_to(e, v, 2) for e in pool) for v in numbers):
            continue
        claims.append(citations.Claim(text=sentence, kind=citations.GENERAL, evidence=[], verified=False,
                                      notes=["not_linked"]))
    return citations.Draft(blocks=[{"type": "paragraph", "claims": claims}])


_SENTENCE_END = re.compile(r"(?<=[.!?؟])\s+")
EVIDENCE_SUMMARY_CHARS = 220
EVIDENCE_MODE_MAX_RELEVANT = 5


def _stems(text: str) -> set:
    """_content_words with a plural folded into its singular ("competitors" matches "competitor"); used to rank
    evidence-mode items, not to admit retrieved chunks."""
    return {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in _content_words(text)}


def _shorten(text: str) -> str:
    return text if len(text) <= EVIDENCE_SUMMARY_CHARS else text[:EVIDENCE_SUMMARY_CHARS].rsplit(" ", 1)[0] + " …"


def _flag_foreign_summary(summary: Optional[dict], mode: str, language: str) -> Optional[dict]:
    """An evidence-mode summary is quoted from the source, so it keeps the source's language: an Arabic question
    about an English document gets an English sentence. Translating it would need the model that is not
    available in this mode, so the answer says so instead (`note`, which the chat words in the user's language).
    A model-written summary already follows the question's language."""
    if summary and mode in ("evidence", "unverifiable") and _language(summary["text"]) != language:
        return {**summary, "note": "source_language"}
    return summary


def _best_sentence(question: str, text: str) -> str:
    """The sentence of `text` sharing most words with `question`, kept short. When none shares a word (a
    question in another language) a single sentence may be only a title, so the start of the text is used."""
    text = " ".join((text or "").split())  # text read from a PDF breaks lines mid-sentence
    sentences = [s for s in _SENTENCE_END.split(text) if s] or [text]
    wanted = _stems(question)
    best = max(sentences, key=lambda s: len(wanted & _stems(s)))  # max keeps the first on a tie
    return _shorten(best if wanted & _stems(best) else text)


# The screens whose records answer each need: a question with several needs ("how did it sell, and how does my
# price compare?") shows the best item for each need first.
_ROUTES_FOR_INTENT = {
    U.SALES: ("/sales",), U.FINANCIALS: ("/sales",), U.PRICING: ("/pricing",),
    U.COMPETITORS: ("/market/competitors", "/pricing"), U.INVENTORY: ("/demand/inventory",), U.FORECAST: ("/demand",),
    U.REVIEWS: ("/market",), U.CUSTOMER_PREFERENCE: ("/market",), U.DOCUMENTS: ("/ai-advisor",),
    U.COMPANY: ("/settings/company", "/ai-advisor"),
}


def _evidence_mode(registry: ev.EvidenceRegistry, language: str, lead: str = "evidence_mode",
                   question: str = "", intents=()) -> citations.Draft:
    """No model wrote this answer: the best-matching evidence is the summary (one sentence), and the
    evidence behind it follows, most relevant first."""
    priority = {ev.PRODUCT_GUIDE: 0, ev.CALCULATION: 1, ev.COMPANY_RECORD: 2, ev.COMPANY_DOCUMENT: 3, ev.WEB_PAGE: 4,
                ev.COMPANY_SUMMARY: 5, ev.USER_INPUT: 9}
    rank = lambda i: -1 if (i.data or {}).get("summary") else priority.get(i.kind, 6)  # noqa: E731
    # Records computed for exactly this question come before anything that merely shares its words (a generated
    # 90-day summary must not lead an answer about last month).
    # named product > the period's headline total > the other records for the question > everything else.
    exact = lambda i: {"named": 0, "headline": 1, "record": 2}.get((i.data or {}).get("exact"), 3)  # noqa: E731
    wanted = _stems(question)
    overlap = lambda i: len(wanted & _stems(f"{i.title} {i.excerpt}"))  # noqa: E731
    # Within the same kind of record, the one whose heading is the question's ("top products by units sold" for
    # "...by units?") comes first.
    titled = lambda i: len(wanted & _stems(i.title))  # noqa: E731
    order = lambda i: (exact(i), -titled(i), -overlap(i), rank(i))  # noqa: E731
    ranked = sorted((i for i in registry.items() if i.kind != ev.USER_INPUT), key=rank)
    # Passages already matched to this question keep room among the 8: a
    # question matching no topic brings every record section, which would
    # otherwise crowd out the one document that answers it.
    documents = [i for i in ranked if i.kind == ev.COMPANY_DOCUMENT][:3]
    # Records are cut to size by how well they match, not by kind alone: the
    # named product's own price record must not lose its place to five
    # "top products" lines that merely come first.
    others = sorted((i for i in ranked if i.kind != ev.COMPANY_DOCUMENT), key=order)
    needs = [_ROUTES_FOR_INTENT[intent] for intent in intents if intent in _ROUTES_FOR_INTENT]
    if len(needs) > 1:
        # One item per need first, so the second half of a combined question isn't cut off by the first.
        lead_items = []
        for routes in needs:
            best = next((i for i in others if i.route in routes and i not in lead_items), None)
            if best is not None:
                lead_items.append(best)
        others = lead_items + [i for i in others if i not in lead_items]
        cap = 8 - len(documents)
        items = documents + others[:cap]
        items = sorted(items, key=lambda i: (i not in lead_items, lead_items.index(i) if i in lead_items else 0,
                                             *order(i)))
    else:
        others = others[:8 - len(documents)]
        items = sorted(documents + others, key=order)
    shares = any(overlap(i) for i in items)
    if shares:
        # Items that share nothing with the question only bury the one that answers it (a supplier agreement
        # under a leave question).
        # Records computed for exactly this question stay even when they share no word with it ("how many did
        # we sell last month?" about the product of the turn before).
        items = [i for i in items if overlap(i) or exact(i) <= 1][:EVIDENCE_MODE_MAX_RELEVANT + max(0, len(needs) - 1)]
    elif wanted:
        # No item shares a word (an Arabic question about English records), so words cannot rank them. A
        # document was matched to the question by meaning before it got here; the record sections were not, so
        # they are shown only when there is no such document.
        matched = [i for i in items if i.kind == ev.COMPANY_DOCUMENT]
        items = matched[:EVIDENCE_MODE_MAX_RELEVANT] or items
    claims = [[citations.Claim(text=f"{item.title}: {' '.join(item.excerpt.split())[:400]}", kind=citations.FACT, evidence=[item.id])]
              for item in items]
    # A summary only when the top item is known to answer the question (it shares words with it, or retrieval
    # matched that document to it); a confident but unrelated line is worse than none.
    top = items[0] if items and wanted and (shares or items[0].kind == ev.COMPANY_DOCUMENT) else None
    summary = ([citations.Claim(text=_best_sentence(question, top.excerpt), kind=citations.FACT, evidence=[top.id])]
               if top else [])
    return citations.Draft(blocks=[
        {"type": "paragraph", "claims": [citations.Claim(text=_LEADS[lead][language], kind=citations.GENERAL,
                                                         evidence=[])]},
        *([{"type": "list", "ordered": False, "items": claims}] if claims else []),
    ], summary=summary)


_RESEARCH_FAILED_AR = {
    public_research.NOT_CONFIGURED: "البحث على الإنترنت غير مُعدّ على هذا الخادم - يحتاج المسؤول إلى إضافة مفتاح مزوّد بحث",
    public_research.SEARCH_FAILED: "فشلت خدمة البحث على الإنترنت",
    public_research.BUDGET_EXHAUSTED: "تم استهلاك حصة البحث على الإنترنت لليوم",
}


def _research_note(statuses: List[dict], language: str) -> Optional[dict]:
    """Evidence mode has no model to explain why the public part is unanswered: say it here."""
    failed = next((s for s in statuses if s["need"] == "public_research" and s["status"] in _RESEARCH_FAILED), None)
    if failed is None:
        return None
    if language == "ar":
        text = f"لم يتمكن KEEL من البحث في المصادر العامة لهذا السؤال: {_RESEARCH_FAILED_AR[failed['status']]}."
    else:
        text = f"KEEL could not research public sources for this question: {_RESEARCH_FAILED[failed['status']]}."
    return {"type": "paragraph", "claims": [citations.Claim(text=text, kind=citations.UNKNOWN, evidence=[])]}


_STATUS_WORDS = {  # the detail already says what is missing; this only names the kind of gap
    "not_permitted": ("{detail} (ask the company owner if you need it).", "{detail} (اطلب ذلك من مالك الشركة إن احتجته)."),
    "none_found": ("Nothing in your records answers this.", "لا يوجد في سجلاتك ما يجيب عن هذا."),
    "none_recorded": ("{detail}.", "{detail}."),
    "failed": ("{detail}.", "{detail}."),
}
_STATUS_DETAIL_AR = {
    "your role can't see": "دورك لا يسمح برؤية",
    "matching documents exist but your role can't open them": "توجد مستندات مطابقة لكن دورك لا يسمح بفتحها",
}


def _status_draft(statuses: List[dict], language: str) -> Optional[citations.Draft]:
    """With no evidence at all, what the statuses establish - a role that may not see the records, records
    that don't exist - said plainly instead of an error. None when they establish nothing."""
    blocked = any(s["status"] == "not_permitted" for s in statuses)
    claims = []
    for status in statuses:
        words = _STATUS_WORDS.get(status["status"])
        if not words or not status.get("detail") or (blocked and status["status"] == "none_found"):
            continue  # "nothing answers this" adds nothing once the role is the reason
        detail = status["detail"]
        if language == "ar":
            for english, arabic in _STATUS_DETAIL_AR.items():
                detail = detail.replace(english, arabic)
        text = (words[1] if language == "ar" else words[0]).format(detail=detail[:1].upper() + detail[1:])
        if all(c.text != text for c in claims):
            claims.append(citations.Claim(text=text, kind=citations.UNKNOWN, evidence=[]))
    note = _research_note(statuses, language)
    if note:
        claims += note["claims"]
    return citations.Draft(blocks=[{"type": "paragraph", "claims": claims}]) if claims else None


def _legacy_sources(references: List[dict]) -> List[dict]:
    """The response's long-standing `sources` list (web sources carry `url`)."""
    out = []
    for ref in references:
        if ref["url"]:
            out.append({"url": ref["url"], "title": ref["title"], "n": ref["n"]})
        else:
            out.append({"source_index": ref["n"], "title": ref["title"], "kind": ref["kind"], "route": ref["route"]})
    return out


_FORMAT_RETRY = ("Your reply had no usable claims (a heading alone is not an answer). Reply again with only the JSON "
                 "object: at least one paragraph, list or table block whose claims cite evidence ids. If the "
                 "evidence does not establish what was asked, say so in an \"unknown\" claim and say what would.")


def _draft(question: str, u: understanding.Understanding, company: dict, access: acl.Access,
           registry: ev.EvidenceRegistry, statuses: List[dict], history: Optional[list], usage: dict,
           regulatory: bool, language: str):
    """(draft, mode, issue count, repaired). The first call's failure is
    raised (evidence mode follows); a failed format or repair round keeps
    what was already verified."""
    compact = False
    messages = _messages(question, u, company, access, registry, statuses, history, compact)
    try:
        raw = _call(messages, usage)
    except llm_client.LLMRequestTooLargeError:
        compact = True
        messages = _messages(question, u, company, access, registry, statuses, history, compact)
        raw = _call(messages, usage, COMPACT_MAX_TOKENS)
    budget = COMPACT_MAX_TOKENS if compact else MAX_TOKENS
    draft = citations.parse_draft(raw)
    if draft is None:
        try:
            raw = _call(messages + [{"role": "assistant", "content": raw[:3000]},
                                    {"role": "user", "content": _FORMAT_RETRY}], usage, budget)
            draft = citations.parse_draft(raw)
        except llm_client.LLMError as err:
            logger.info("format retry failed: %s", type(err).__name__)
    if draft is None and raw.lstrip().startswith("{"):
        # JSON that carries no claim (a heading only): showing it as text would print the JSON itself.
        return (_evidence_mode(registry, language, lead="unverifiable", question=u.effective_question,
                               intents=u.intents), "unverifiable", 0, False)
    if draft is None:
        return _fallback_draft(raw, registry, language), "unlinked", 0, False
    draft, issues = citations.validate(draft, registry, user_text=question, regulatory=regulatory)
    if not issues:
        return draft, "ai", 0, False
    try:
        retry = _call(messages + [{"role": "assistant", "content": raw[:4000]},
                                  {"role": "user", "content": citations.repair_prompt(issues)}], usage, budget)
    except llm_client.LLMError as err:
        logger.info("repair round failed, keeping the checked draft: %s", type(err).__name__)
        return draft, "ai", len(issues), False
    second = citations.parse_draft(retry)
    if second is not None:
        second, second_issues = citations.validate(second, registry, user_text=question, regulatory=regulatory)
        if len(second_issues) <= len(issues) and any(b["type"] != "heading" for b in second.blocks):
            return second, "ai", len(second_issues), True
    return draft, "ai", len(issues), False


def answer(conn, tenant_id: str, question: str, top_k: int = 5, history: Optional[list] = None,
           user_id: Optional[str] = None, access: Optional[acl.Access] = None, state: Optional[dict] = None,
           enable_research: bool = True, include_structured_facts: bool = True,
           research_kwargs: Optional[dict] = None, use_ai: bool = True, **_ignored) -> dict:
    """The cited answer to `question` for this company and member.

    `question` and `history` may be any length: what doesn't fit the prompt
    is recalled by relevance (_recall()). use_ai=False (the company's AI
    allowance is used up) answers from the evidence alone, with no paid call.

    Returns {"answer", "answer_blocks", "references", "sources", "follow_up_questions", "calculations",
    "evidence_status", "research", "state", "answer_mode", "token_usage", "citation_check"}."""
    access = access or (acl.load_access(conn, tenant_id, user_id) if user_id else acl.FULL_ACCESS)
    full_question = question
    question = conversation_memory.focus(full_question)
    history, older, recent_full = _split_history(history)
    language = _language(question)
    company = _company(conn, tenant_id)
    catalog = _catalog(conn, tenant_id, access) if include_structured_facts else []
    today = business_today(conn) if conn is not None else datetime.now(timezone.utc).date()
    u = understanding.understand(question, previous=state, catalog=catalog, company_currency=company.get("currency"),
                                 today=today)
    registry = ev.EvidenceRegistry()
    statuses: List[dict] = []
    # "My top product" names a product for another question ("would importing my top product be cheaper?").
    # "What was my top selling product this year by units?" IS the ranking: the sales records answer it, and
    # naming the 90-day revenue leader as "the product asked about" would answer a different question.
    ranking = U.SALES in u.intents or bool(u.slots.get("periods") or u.slots.get("period_days"))
    if u.slots.get("top_product") and not u.slots.get("products") and not ranking:
        top = _top_product(conn, tenant_id, catalog, access)
        if top:
            # Only the product's name goes on to research queries - never its figures.
            u.slots["products"] = [{"product_id": top["product_id"], "name": top["name"]}]
        elif not access.allows(acl.SALES):
            _status(statuses, "top_product", "not_permitted", "your role can't see sales, which rank the products")
        else:
            _status(statuses, "top_product", "none_found", "no sales recorded in the last 90 days to rank products by")
    answerable = understanding.is_answerable(question) or u.follow_up

    user_ids = _user_inputs(registry, question, state, u.follow_up, language)
    _recall(registry, question, full_question, older, recent_full, language)
    guide = product_guide.build_guide_block(question)
    if guide:
        items = registry.add_fact_lines(guide.splitlines(), route=None, capabilities=frozenset(),
                                        kind=ev.PRODUCT_GUIDE, credibility=ev.PRIMARY, title="KEEL product guide")
        for item, screen in zip(items, product_guide.guide_screens(question)):
            item.route = screen

    company_found = 0
    products: Dict[str, dict] = {}
    if answerable and include_structured_facts:
        for intent in u.intents:
            missing = access.missing(*_CAPABILITY_FOR_INTENT.get(intent, ()))
            if missing:
                _status(statuses, intent, "not_permitted", f"your role can't see {', '.join(sorted(missing))}")
        search = u.effective_question
        if U.COMPANY in u.intents:
            # The company's own profile document answers "tell me about my company" in any wording or language.
            search += " company profile"
        exact, replaced = (0, frozenset())
        if not u.public_scope:  # "the average water price" needs no sales or price-gap records
            exact, replaced = _records(conn, tenant_id, u, access, registry, statuses, language, today)
            company_found += exact
        company_found += _documents(conn, tenant_id, search, access, registry, top_k, statuses, language,
                                    intents=u.intents, superseded=replaced)
        if not u.public_scope:
            company_found += _fact_sections(conn, tenant_id, u, access, registry, statuses, skip=replaced)
            company_found += _analysis(conn, tenant_id, u, access, registry, exact_sales="sales" in replaced)
        company_found += _catalogue_record(u, catalog, access, registry, language)
        products = _product_records(u, catalog, access, registry, language)
        company_found += len(products)
        company_found += _reviews(conn, tenant_id, u, access, registry, statuses, language)

    ask = None
    if use_ai and llm_client.provider_configured():
        ask = _guarded(llm_client.chat_completion)
    if not use_ai:
        enable_research = False  # research is paid for too
    research_result = None
    # "Price" or "cost" alone is not a private question: "the average water price" is about the world.
    private_only = bool(u.intents) and set(u.intents) <= _PRIVATE_ONLY and not u.public_scope
    wants_research = u.needs_research or (answerable and not guide and not private_only and company_found == 0)
    if wants_research and enable_research and conn is not None and answerable:
        research_result = public_research.research(conn, tenant_id, registry, u.effective_question, u.intents,
                                                   u.slots, company, ask=ask, language=language,
                                                   **(research_kwargs or {}))
        _status(statuses, "public_research", research_result.status, research_result.detail or "")
    elif wants_research and not enable_research:
        _status(statuses, "public_research", "not_attempted")
    if private_only and company_found == 0 and answerable and not guide:
        _status(statuses, "company_records", "none_found",
                "nothing in the company's records answers this; public research cannot reveal private figures")

    calculation = None
    if U.LANDED_COST in u.intents or (U.TRADE in u.intents and u.slots.get("amounts")):
        rates = _extract_rates(ask, registry, research_result.evidence if research_result else [], u,
                               company.get("currency") or "JOD")
        calculation = _calculation(u, registry, user_ids, products, company, rates, statuses, language)

    usage: Dict[str, int] = {}
    regulatory = bool({U.REGULATION, U.TRADE, U.LANDED_COST} & set(u.intents))
    mode, repaired, issue_count = "ai", False, 0
    if not use_ai:
        draft, mode = _evidence_mode(registry, language, lead="allowance_used", question=u.effective_question, intents=u.intents), "evidence"
        _status(statuses, "answer_writing", "allowance_used")
    else:
        try:
            with _server_refusals_as_llm_errors():
                draft, mode, issue_count, repaired = _draft(question, u, company, access, registry, statuses,
                                                            history, usage, regulatory, language)
        except llm_client.LLMError as err:
            if not len(registry) and _status_draft(statuses, language) is None:
                raise
            logger.warning("Assistant answered in evidence mode (tenant=%s): %s", tenant_id, err)
            draft, mode = _evidence_mode(registry, language, question=u.effective_question, intents=u.intents), "evidence"
            reason = ("not_configured" if isinstance(err, llm_client.LLMNotConfiguredError)
                      else "provider_busy" if isinstance(err, (llm_client.LLMRateLimitError,
                                                               llm_client.LLMRequestTooLargeError))
                      else "provider_unavailable")
            _status(statuses, "answer_writing", reason)

    registry.localize_titles(language)
    if not len(registry) and mode in ("evidence", "unverifiable"):
        draft = _status_draft(statuses, language) or draft
    note = _research_note(statuses, language) if mode in ("evidence", "unverifiable") and len(registry) else None
    if note:
        draft.blocks.insert(1 if draft.blocks and draft.blocks[0]["type"] == "paragraph" else 0, note)
    if not any(block["type"] != "heading" for block in draft.blocks):
        # Every claim failed its check: show what was found instead of an empty reply.
        draft, mode = _evidence_mode(registry, language, lead="unverifiable", question=u.effective_question, intents=u.intents), "unverifiable"
    rendered = citations.render(draft, registry, always=[calculation["evidence_id"]] if calculation else [])
    if calculation:
        calculation["ref"] = rendered["numbering"].get(calculation["evidence_id"])
    # One countable line per answer: how often a summary is shown, written by the model or built from the
    # answer, how often the checks drop the model's, and how often the repair round runs.
    # An evidence-mode summary is a sentence quoted from the evidence, not written by the model: counting it as
    # "model" would inflate the share of answers whose summary the model wrote.
    summary_source = rendered["summary_source"]
    if summary_source == "model" and mode in ("evidence", "unverifiable"):
        summary_source = "extractive"
    logger.info("assistant_answer mode=%s summary=%s dropped=%d issues=%d repaired=%s", mode,
                summary_source, rendered["summary_dropped"], issue_count, repaired)
    return {
        "answer": rendered["answer"], "answer_summary": _flag_foreign_summary(rendered["summary"], mode, language), "answer_blocks": rendered["blocks"], "references": rendered["references"],
        "sources": _legacy_sources(rendered["references"]), "follow_up_questions": rendered["follow_up_questions"],
        "calculations": [calculation] if calculation else [], "evidence_status": statuses,
        "research": research_result.summary() if research_result else None, "state": u.state(),
        "answer_mode": mode, "token_usage": {"prompt_tokens": usage.get("prompt_tokens", 0),
                                             "completion_tokens": usage.get("completion_tokens", 0),
                                             "total_tokens": usage.get("total_tokens", 0)},
        "citation_check": {"issues": issue_count, "repaired": repaired},
    }
