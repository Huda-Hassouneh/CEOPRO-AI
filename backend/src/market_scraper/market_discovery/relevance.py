"""
How each discovered business relates to the company - and why.

- DIRECT: sells the same thing to the same customers. Evidence: one of the
  company's products found on its site at a published price, or the
  company's specialty (from its own products and description - "mansaf",
  "shawarma", "middle eastern" for a Jordanian restaurant) in its category
  or name; for a business type outside KEEL's industry list, its own trade
  words in the category or name.
- INDIRECT: the same industry, without evidence of the same specialty (an
  Italian restaurant for a mansaf restaurant): competes for the same budget.
- RELATED: a neighbouring industry (a café for a restaurant).
- UNVERIFIED: found by a search or a name match only, with no category to
  confirm what it does.

Every label carries its reasons ({"code", ...}) so the screen can say why.
Specialty words come from the company's own product names and description,
plus (once per profile, when the configured AI model answers) the words a
business selling the same things would use in its category or name.
"""
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

from src.market_scraper.category_taxonomy import MIN_COMPETING_SIMILARITY, best_similarity, categorize
from src.market_scraper.market_discovery import industries
from src.market_scraper.market_discovery.offerings import _word_in, normalize, tokens

logger = logging.getLogger("KEEL_MARKET_DISCOVERY")
DIRECT, INDIRECT, RELATED, UNVERIFIED = "DIRECT", "INDIRECT", "RELATED", "UNVERIFIED"
RELATIONSHIPS = (DIRECT, INDIRECT, RELATED, UNVERIFIED)
_SCORE_SHIFT = {DIRECT: 0.12, INDIRECT: 0.0, RELATED: -0.12, UNVERIFIED: -0.2}
_TERMS_CACHE: Dict[str, Tuple[str, ...]] = {}
# Words that say "a business" or the whole industry, never a specialty.
_GENERAL = {"restaurant", "restaurants", "food", "shop", "store", "company", "services", "service", "center", "centre",
            "cafe", "coffee", "hotel", "clinic", "pharmacy", "office", "market", "supermarket", "bakery", "sweets",
            "مطعم", "مطاعم", "محل", "متجر", "شركه", "خدمات", "مركز", "مقهي", "فندق", "عياده", "صيدليه", "مكتب", "سوق",
            # generic venue words a model may still suggest
            "house", "place", "joint", "stall", "kitchen", "corner", "spot", "eatery", "diner", "bistro", "outlet",
            "branch", "local", "family", "traditional", "authentic", "home", "street", "express",
            "app", "apps", "plan", "plans", "support", "care", "health", "pro", "plus", "online", "digital", "group",
            "solution", "system", "systems", "product", "products", "item", "items", "quality", "premium",
            "بيت", "ماكولات", "اكلات", "مطبخ", "ركن", "زاويه", "فرع", "بلدي", "شعبي", "تقليدي"}


def ai_hints_enabled() -> bool:
    """DISCOVERY_AI_HINTS=false: no AI model is asked for specialty words,
    product aliases or category words (tests, or a deployment without one)."""
    return os.getenv("DISCOVERY_AI_HINTS", "true").lower() not in ("0", "false", "no")


def specialty_terms(profile: dict, query, ask=None) -> Tuple[str, ...]:
    """Normalised words that name what this company specifically sells."""
    products = [p for p in profile.get("product_names") or [] if p]
    description = " ".join(filter(None, [profile.get("business_type"), profile.get("business_description")]))
    key = normalize(f"{description} | {' ; '.join(sorted(products))}")
    if key in _TERMS_CACHE:
        return _TERMS_CACHE[key]
    words = set()
    for text in products + ([profile.get("business_type")] if query.industry_key != industries.CUSTOM else []):
        words.update(tokens(text))
    try:
        if ask is None:
            if not ai_hints_enabled():
                raise LookupError("AI hints off")
            from src.ai.rag import llm_client
            ask = llm_client.chat_completion
        answer = ask([
            {"role": "system", "content": "You help find a business's direct competitors on maps and listings. Given what a "
                                          "business is and sells, answer with only JSON {\"en\": [...], \"ar\": [...]}: up to 8 "
                                          "short lowercase English words and up to 6 Arabic words that would appear in the "
                                          "category or name of a business selling the SAME specific things: the cuisine "
                                          "or specialty (e.g. middle eastern, levantine, lebanese) and the signature "
                                          "products (e.g. shawarma, mansaf). Never generic venue words (house, place, "
                                          "kitchen, corner, joint, shop, food), no country or city names, no brand names, "
                                          "and not the general industry word."},
            {"role": "user", "content": f"Business: {description or query.industry_label}\nProducts: {', '.join(products[:12]) or '-'}"},
        ], temperature=0, max_tokens=700)
        listed = json.loads(re.search(r"\{.*\}", answer, re.S).group(0))
        for phrase in (listed.get("en") or []) + (listed.get("ar") or []):
            if isinstance(phrase, str):
                words.update(tokens(phrase))
    except Exception as exc:  # noqa: BLE001 - product words alone still work
        logger.info("no specialty words for this profile: %s", type(exc).__name__)
    terms = tuple(sorted(w for w in words if len(w) >= 3 and w not in _GENERAL))
    _TERMS_CACHE[key] = terms
    return terms


def _category_text(categories: List[str]) -> str:
    return normalize(" ".join(c.split(":", 1)[-1].split("=", 1)[-1].replace("_", " ") for c in categories or []))


def classify(name: str, name_ar: Optional[str], categories: List[str], fit_reason: Optional[str], query,
             terms: Tuple[str, ...], priced_matches: int = 0) -> Tuple[str, List[dict]]:
    """(relationship, reasons) for one business."""
    reasons: List[dict] = []
    if priced_matches:
        return DIRECT, [{"code": "same_products", "count": priced_matches}]
    category_text = _category_text(categories)
    name_text = normalize(f"{name} {name_ar or ''}")
    category_words, name_words = set(category_text.split()), set(name_text.split())
    for term in terms:
        if _word_in(term, list(category_words)) or (" " in term and term in category_text):
            reasons.append({"code": "same_specialty", "term": term, "where": "category"})
        elif _word_in(term, list(name_words)) or any(w.startswith(term) for w in name_words if len(term) >= 4):
            reasons.append({"code": "same_specialty", "term": term, "where": "name"})
    if reasons:
        return DIRECT, reasons[:3]
    if query.industry_key == industries.CUSTOM and fit_reason in ("same_industry", "keyword"):
        # The owner's own trade words are what matched: as specific as it gets.
        return DIRECT, [{"code": "same_trade"}]
    if fit_reason == "same_industry":
        return INDIRECT, [{"code": "same_industry"}]
    if fit_reason == "related_industry":
        return RELATED, [{"code": "related_industry"}]
    if fit_reason == "keyword" and categories:
        return INDIRECT, [{"code": "name_matches_industry"}]
    return UNVERIFIED, [{"code": "not_confirmed"}]


def adjusted_score(relevance: float, relationship: str) -> float:
    return max(0.0, min(1.0, relevance + _SCORE_SHIFT.get(relationship, 0.0)))


def specific_categories(categories: List[str], query) -> set:
    """A business's listing categories minus the industry's generic ones
    ("restaurant", "fast_food" for any restaurant)."""
    generic = {v.lower() for _k, v in query.osm_tags} | {v.lower() for v in query.google_types} | {
        (query.industry_key or "").lower(), "restaurant", "shop", "store", "food", "cafe", "professional_service",
        "corporate_or_business_office", "point_of_interest", "establishment", "yes"}
    out = set()
    for raw in categories or []:
        name = raw.split(":", 1)[-1].split("=", 1)[-1].lower()
        if raw.startswith(("overture:", "amenity=", "shop=", "cuisine=", "office=", "craft=", "tourism=", "healthcare=")) \
                and name and name not in generic:
            out.add(name)
    return out


def specialty_categories(named: List[Tuple[List[str], str]], query, min_count: int = 2) -> set:
    """Specific categories shared by at least `min_count` of the businesses
    whose name shows the company's specialty - the market's own label for it."""
    counts: Dict[str, int] = {}
    for categories, _relationship in named:
        for name in specific_categories(categories, query):
            counts[name] = counts.get(name, 0) + 1
    return {name for name, n in counts.items() if n >= min_count}


def in_different_category(name: str, name_ar: Optional[str], categories: List[str], query) -> bool:
    """True when this business is in a different SEGMENT from the company
    (a donut shop for a burger restaurant: food > desserts vs. food >
    snacks) - not a competitor even though both are "restaurants". Only a
    positive mismatch counts: if the company's segment or the business's
    category is unknown, nothing is ruled out. Callers keep a business that
    has stronger evidence (same products at a published price, or the
    company's own specialty) regardless."""
    paths = getattr(query, "category_paths", ()) or ()
    if not paths:
        return False
    types, words = [], []
    for raw in categories or []:
        value = raw.split(":", 1)[-1].split("=", 1)[-1].lower()
        types.append(value)
        words.append(value.replace("_", " "))
    categorization = categorize(" ".join([name or "", name_ar or "", *words]), types)
    if categorization is None:
        return False
    similarity = best_similarity(paths, categorization.path)
    return similarity is not None and similarity < MIN_COMPETING_SIMILARITY
