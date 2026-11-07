"""
KEEL - question understanding with a language model, as a second reader behind the rules.

understanding.py reads a question with deterministic rules: fast, free and exact when it knows the wording,
but blind to wordings it has never seen (a dialect spelling, an idiom, a word used in another sense). This
module asks the configured language model (llm_client.chat_completion: Groq, a local llama.cpp server, ...)
to read the same question into the same fields, and uses its reading only where the rules found nothing:

- no intent, or only the generic "products" (a word like "item" or "صنف") -> the model's intents
- the model reads a strict subset of the rules' intents -> the rules' extra ones are dropped
- no period  -> the model's periods, written in plain English ("Q2 2026", "since June 2026") and turned into
                exact dates by periods.py - the model never does date arithmetic
- no product -> the model's choice from the catalogue names it was shown (never a name it made up)
- ranking    -> either reader may say a ranking is asked for
- small talk -> the model decides only when the rules found no business need

Off by default (RAG_LLM_UNDERSTANDING=off); "gaps" turns it on. Any failure of the model (not configured,
down, slow, malformed answer) leaves the rules' reading unchanged - this step can only add, never block.

Measured 2026-11-05 on a sealed 149-question set (English, MSA, Jordanian, Levantine, Egyptian, Gulf, mixed),
Qwen3-4B-Instruct on CPU: rules 81.2% of questions read right in every field, model alone 60.4%, this
combination 87.9% (docs/AI_MODEL_ACCURACY.md).
"""
import json
import logging
import os
import re
from datetime import date
from typing import List, Optional

from src.ai.rag import periods as _periods
from src.ai.rag import understanding as U

logger = logging.getLogger("CEOPRO_AI_RAG_LLM_UNDERSTANDING")

MODE = os.getenv("RAG_LLM_UNDERSTANDING", "off").strip().lower()
TIMEOUT_SECONDS = float(os.getenv("RAG_LLM_UNDERSTANDING_TIMEOUT_SECONDS", "60"))
MAX_CATALOG_NAMES = int(os.getenv("RAG_LLM_UNDERSTANDING_CATALOG_NAMES", "15"))
MAX_TOKENS = 320

INTENT_MEANINGS = {
    U.SALES: "revenue, sales, orders, invoices, units sold, best or worst sellers, money brought in; also customer "
             "debts, unpaid or outstanding invoices and payments received (they are read from the invoices)",
    U.FINANCIALS: "profit, net profit, margin, cost price, expenses, losses",
    U.PRODUCTS: "the product catalogue itself (how many products, list them)",
    U.PRICING: "a product's selling price, what we charge",
    U.INVENTORY: "stock on hand, out of stock, items missing or empty, reorder or restock from a supplier, availability",
    U.FORECAST: "future demand (how much customers will want), predictions, next month",
    U.COMPETITORS: "competitors and their prices",
    U.REVIEWS: "customer reviews, ratings, satisfaction, complaints, unhappy customers",
    U.DOCUMENTS: "company policies and documents: returns, refunds, delivery, warranty, terms and conditions of sale, "
                 "instalments, contracts",
    U.COMPANY: "the company itself: profile, history, branches, what it does",
    U.PRODUCT_RESEARCH: "who else sells a product, suppliers",
    U.MARKET_RESEARCH: "the wider market, trends",
    U.ADVICE: "asks what to do",
}

_SYSTEM = (
    "You convert a business owner's question (English, Arabic in any dialect, or mixed) into JSON. Today is {today}.\n"
    "Keys: intents (list, from: {intents}), periods (list of calendar periods the question names, each written in plain "
    "English using ONLY these forms: 'today', 'yesterday', 'this month', 'last month', 'this year', 'last year', "
    "'last quarter', '<Month> <YYYY>', 'Q<n> <YYYY>', 'H<n> <YYYY>', '<YYYY>', 'since <Month> <YYYY>', "
    "'from <D Month YYYY> to <D Month YYYY>', 'last <N> days'), products (list of exact names from the catalogue that "
    "the question is about; [] if none), ranking (true if it asks which products sell most/least/best), small_talk "
    "(true for greetings/thanks only).\nIntent meanings: {meanings}\nThe user message gives the catalogue, then the "
    "question. Answer with JSON only."
)


def parse_json_object(raw) -> Optional[dict]:
    """The JSON object in a model's answer: the whole answer, or the first {...} in it (some models add a word or a
    code fence around it). None when there is no complete object."""
    if not isinstance(raw, str):
        return None
    for candidate in (raw.strip(), raw[raw.find("{"):raw.rfind("}") + 1] if "{" in raw else ""):
        try:
            value = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


# Worked examples shown to the model before every question (dialects, idioms and words used in another sense). Drawn
# only from development questions - never from a sealed test set. RAG_LLM_UNDERSTANDING_EXAMPLES=off removes them.
EXAMPLES_ON = os.getenv("RAG_LLM_UNDERSTANDING_EXAMPLES", "on").strip().lower() != "off"
_EXAMPLES = [
    ("قديش بعنا بشهر تشرين الأول؟", {"intents": ["sales"], "periods": ["October 2026"]}),
    ("بعنا كام امبارح؟", {"intents": ["sales"], "periods": ["yesterday"]}),
    ("شنو مبيعاتنا هالشهر؟", {"intents": ["sales"], "periods": ["this month"]}),
    ("الـ revenue تبع Q1", {"intents": ["sales"], "periods": ["Q1 2026"]}),
    ("شو الصنف اللي ما بيمشي عنا؟", {"intents": ["sales"], "ranking": True}),
    ("مين أكثر منتج بيجيب فلوس؟", {"intents": ["sales"], "ranking": True}),
    ("قديه ضل عنا دبس رمان؟", {"intents": ["inventory"], "products": ["Pomegranate Molasses 300ml"]}),
    ("فاضل عندنا كام كيس مفتول؟", {"intents": ["inventory"], "products": ["Maftoul 500g"]}),
    ("كم متوقع نبيع طحينة الشهر الجاي؟", {"intents": ["forecast"], "products": ["Tahini 450g"]}),
    ("بكام بنبيع الفريكة؟", {"intents": ["pricing"], "products": ["Freekeh 1kg"]}),
    ("What price do we sell Tahini 450g at?", {"intents": ["pricing"], "products": ["Tahini 450g"]}),
    ("كسبنا قد إيه في الربع التالت؟", {"intents": ["financials"], "periods": ["Q3 2026"]}),
    ("شو رأي الزباين بالتوصيل؟", {"intents": ["reviews"]}),
    ("ينفع الزبون يرجع المنتج؟", {"intents": ["documents"]}),
    ("Who sells olive oil cheaper than us?", {"intents": ["competitors"]}),
    ("قارنلي مبيعات الربع الأول والتاني", {"intents": ["sales"], "periods": ["Q1 2026", "Q2 2026"]}),
    ("sales since June", {"intents": ["sales"], "periods": ["since June 2026"]}),
    ("شكرا جزيلا", {"intents": [], "small_talk": True}),
    # Jordanian round 2 (from dev_jo2 only): debts, "فش" = none left, orders, terms of sale, complaints, demand
    ("مين الناس اللي لسا ما دفعوا؟", {"intents": ["sales"]}),
    ("فش طحينة؟", {"intents": ["inventory"], "products": ["Tahini 450g"]}),
    ("عدد الطلبيات تبع مبارح", {"intents": ["sales"], "periods": ["yesterday"]}),
    ("شو سياسة البيع بالتقسيط؟", {"intents": ["documents"]}),
    ("في حدا زعلان منا؟", {"intents": ["reviews"]}),
    ("قديش رح يطلبوا الناس قهوة بالعيد؟", {"intents": ["forecast"]}),
]


def _example_turns(today: date) -> List[dict]:
    """The worked examples as earlier turns. Their dates follow `today`, so "this month" stays this month."""
    if not EXAMPLES_ON:
        return []
    turns = []
    for question, answer in _EXAMPLES:
        full = {"intents": [], "periods": [], "products": [], "ranking": False, "small_talk": False, **answer}
        full["periods"] = [p.replace("2026", str(today.year)) for p in full["periods"]]
        turns += [{"role": "user", "content": f"Catalogue: (as below)\nQuestion: {question}"},
                  {"role": "assistant", "content": json.dumps(full, ensure_ascii=False)}]
    return turns


# Words that name a time. A question with one and no period the rules could read needs the model.
_TIME_WORDS = re.compile(r"(?<![a-z])(?:since|from|until|between|last|this|next|ago|week|month|quarter|year|today|"
                         r"yesterday|days?|weeks?|q[1-4]|h[12]|\d{1,2}[/-]\d{2,4})(?![a-z])|"
                         r"(?:منذ|من اول|من بدايه|لحد|لغايه|حتى|اسبوع|جمعه|شهر|ربع|سنه|عام|امس|مبارح|اليوم|النهارده|ايام|يوم|"
                         r"هلق|هسا|الماضي|الجاي|القادم|فات)")


def needs_model(u: "U.Understanding", question: str) -> bool:
    """Whether the rules' reading is uncertain enough to ask the model (seconds) rather than answer from the rules
    alone (milliseconds). Asked when the rules found no need, only the generic catalogue need, several needs (one
    may come from a word used in another sense), a time word without a period, or a price question without a
    product. Measured 2026-11-06 on three development pools before adopting it (docs/AI_MODEL_ACCURACY.md)."""
    if U.is_greeting(question):
        return False  # a greeting the rules recognise needs no reading
    intents = set(u.intents)
    if not intents or intents <= {U.PRODUCTS} or len(intents - {U.PRODUCTS}) > 1:
        return True
    has_period = bool(u.slots.get("periods") or u.slots.get("period_days") or u.slots.get("all_history"))
    if not has_period and _TIME_WORDS.search(U._norm(question)):
        return True
    if U.PRICING in intents and not u.slots.get("products"):
        return True
    return False


def enabled() -> bool:
    return MODE == "gaps"


def _tokens(text: str) -> set:
    words = re.findall(r"[\w؀-ۿ]{2,}", U._norm(text))
    return {w[2:] if w.startswith("ال") and len(w) > 4 else w for w in words}


def catalog_candidates(question: str, catalog: List[dict], limit: int = MAX_CATALOG_NAMES) -> List[dict]:
    """The catalogue products most likely meant, for the prompt: a large catalogue cannot be shown whole. Ranked
    by shared words and shared 3-letter pieces (dialect spellings and attached Arabic prefixes still overlap)."""
    q_tokens = _tokens(question)
    q_grams = {t[i:i + 3] for t in q_tokens for i in range(max(1, len(t) - 2))}

    def score(product: dict) -> float:
        names = " ".join(filter(None, (product.get("name"), product.get("name_alt"))))
        tokens = _tokens(names)
        grams = {t[i:i + 3] for t in tokens for i in range(max(1, len(t) - 2))}
        return 3 * len(q_tokens & tokens) + len(q_grams & grams) / max(1, len(grams)) * 2

    return sorted(catalog, key=score, reverse=True)[:limit]


def read(question: str, catalog: Optional[List[dict]] = None, today: Optional[date] = None) -> Optional[dict]:
    """The model's reading of `question`, validated: intents from the known list only, periods resolved to exact
    dates, products from the catalogue only. None when the model is unavailable or answers nonsense."""
    from src.ai.rag import llm_client

    today = today or date.today()
    shown = catalog_candidates(question, catalog or [])
    # The instructions are the same for every question (a server can reuse their processing); the catalogue
    # names chosen for this question go in the user message with it.
    system = _SYSTEM.format(today=today.isoformat(), intents=", ".join(INTENT_MEANINGS),
                            meanings="; ".join(f"{k}: {v}" for k, v in INTENT_MEANINGS.items()))
    names_text = "; ".join(f"{p['name']} ({p['name_alt']})" if p.get("name_alt") else p["name"] for p in shown) or "(none)"
    messages = [{"role": "system", "content": system}, *_example_turns(today),
                {"role": "user", "content": f"Catalogue: {names_text}\nQuestion: {question}"}]
    out = None
    for attempt in range(2):
        try:
            raw = llm_client.chat_completion(messages, temperature=0, max_tokens=MAX_TOKENS, timeout=TIMEOUT_SECONDS,
                                             json_mode=True)
        except Exception as err:  # noqa: BLE001 - the rules' reading stands
            logger.warning("model reading unavailable (%s); using the rules only", type(err).__name__)
            return None
        out = parse_json_object(raw)
        if out is not None:
            break
        # One stricter retry: a cut-off or chatty answer is usually right the second time.
        messages = messages + [{"role": "assistant", "content": str(raw)[:400]},
                               {"role": "user", "content": "That was not one complete JSON object. Reply with the JSON object only."}]
    if out is None:
        logger.warning("model reading was not valid JSON twice; using the rules only")
        return None
    if not isinstance(out, dict):
        return None
    names = {p["name"]: p for p in shown}

    def strings(key) -> List[str]:
        """A list of strings from the model, whatever it actually sent (a small model sometimes sends objects)."""
        value = out.get(key)
        if isinstance(value, str):
            value = [value]
        return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []

    resolved, days = [], None
    for phrase in strings("periods"):
        text = U._norm(phrase)
        resolved += _periods.resolve_periods(text, today)
        days = days or _periods.rolling_days(text)
    return {
        "intents": [i for i in strings("intents") if i in INTENT_MEANINGS],
        "periods": resolved,
        "period_days": days if not resolved else None,
        "products": [{"product_id": names[n]["product_id"], "name": n} for n in strings("products") if n in names],
        "ranking": out.get("ranking") is True,
        "small_talk": out.get("small_talk") is True,
    }


def fill_gaps(u: "U.Understanding", reading: Optional[dict]) -> "U.Understanding":
    """`u` with what the rules left empty filled from the model's `reading` (see the module docstring). Records
    which fields came from the model in u.slots['read_by_model'] (for logs and evaluation)."""
    if not reading:
        return u
    filled = []
    if not u.intents and reading["intents"]:
        u.intents = list(reading["intents"]); filled.append("intents")
    elif set(u.intents) <= {U.PRODUCTS} and set(reading["intents"]) - {U.PRODUCTS}:
        # The rules saw only a generic product word ("item", "صنف"): the weakest reading they make.
        u.intents = list(reading["intents"]); filled.append("intents")
    elif reading["intents"] and set(reading["intents"]) < set(u.intents) \
            and not U.explicitly_compound(u.effective_question or ""):
        # (Never when the question joins two needs itself - "قديش بعنا وقديش ربحنا؟" keeps both.)
        # The model read fewer of the same needs: the rules' extra ones came from a word used in another sense
        # ("what price do we SELL it at", "how much does delivery COST", "when SHOULD I reorder").
        u.intents = [i for i in u.intents if i in reading["intents"]]; filled.append("intents")
    if not u.slots.get("periods") and not u.slots.get("period_days"):
        if reading["periods"]:
            u.slots["periods"] = reading["periods"][:4]; filled.append("periods")
        elif reading["period_days"]:
            u.slots["period_days"] = reading["period_days"]; filled.append("periods")
    if not u.slots.get("products") and reading["products"]:
        u.slots["products"] = reading["products"]; filled.append("products")
    if reading["ranking"] and not u.slots.get("ranking_requested"):
        u.slots["ranking_requested"] = True; filled.append("ranking")
    if filled:
        u.slots["read_by_model"] = filled
    return u


def answerable(rules_answerable: bool, rules_found_intent: bool, reading: Optional[dict]) -> bool:
    """Small talk is the rules' call while they found a business need; otherwise the model's ("thanks, that's
    helpful" has no need the rules know, and is not a question either)."""
    if rules_found_intent or not reading:
        return rules_answerable
    return not reading["small_talk"] and bool(reading["intents"])
