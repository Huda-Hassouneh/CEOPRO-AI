"""
Settles the one question the rules cannot: when a product's name is a competitor item's name plus extra words
("conversation class" / "class", "cheese burger" / "burger"), are the extra words something ADDED (a feature,
topping, service - a higher price can be justified) or only a different VARIANT of the same standing?

Asked of the configured AI model only for those pairs, only when DISCOVERY_AI_HINTS allows it, with a capped number
of questions per run (PRICE_COMPARISON_AI_MAX_PAIRS), a cached answer per pair, and a strict one-word answer. The
model never sees or produces a price. No model, no answer, or an unclear answer leaves the pair unsettled, and an
unsettled pair is shown as similar and is kept out of pricing recommendations.
"""
import logging
import os
import re
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger("KEEL_PRICE_COMPARISON")
MAX_PAIRS_PER_RUN = int(os.getenv("PRICE_COMPARISON_AI_MAX_PAIRS", "60"))
_CACHE: Dict[Tuple[str, str, str], Optional[str]] = {}

_SYSTEM = (
    "You compare two product or service names from a menu or price list. Name A is the business's own item; name B is "
    "a competitor's. One name equals the other plus extra words. Decide whether the extra words describe something "
    "ADDED to the base item - an ingredient, topping, feature, service or bonus that gives the customer more and can "
    "justify a higher price - or only a different VARIANT/flavour/type of comparable standing (e.g. chicken instead of "
    "beef). Answer with exactly one word: addition or variant."
)


def model_judge(own_name: str, item_name: str, side: str, words) -> Optional[str]:
    """"addition" | "variant" | None (no model, not allowed, or unclear)."""
    key = (own_name.strip().lower(), item_name.strip().lower(), side)
    if key in _CACHE:
        return _CACHE[key]
    answer = None
    try:
        from src.market_scraper.market_discovery.relevance import ai_hints_enabled

        if ai_hints_enabled():
            from src.ai.rag import llm_client

            reply = llm_client.chat_completion([
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"A (business's own): {own_name}\nB (competitor's): {item_name}\nExtra words on "
                                            f"{'A' if side == 'own' else 'B'}: {', '.join(words)}"},
            ], temperature=0, max_tokens=5)
            found = re.search(r"\b(addition|variant)\b", (reply or "").lower())
            answer = found.group(1) if found else None
    except Exception as exc:  # noqa: BLE001 - matching works without a model
        logger.info("price comparison: no AI verdict (%s)", type(exc).__name__)
        return None  # not cached: a later run may have a model
    _CACHE[key] = answer
    return answer


Judge = Callable[[str, str, str, list], Optional[str]]
