"""Does a listing's title describe OUR product? Conservative on purpose: a
wrong price is worse than no price, so every digit-bearing token of our name
(model number, size, volume - "dt830b", "500g") must appear in the listing,
and at least MIN_SCORE of all meaningful words must."""
import re
from typing import Iterable, Optional, Set

MIN_SCORE = 0.7
# A listing that carries our exact size/model AND our leading (brand) word is the
# same product even when it omits descriptive words ("Nutella 400 g" for "Nutella
# Hazelnut Spread 400g"): it is accepted from this share of words upward.
ANCHORED_MIN_SHARE = 0.5
_STOP = {"the", "a", "an", "and", "or", "of", "for", "with", "in", "to", "pack", "new", "من", "في", "مع", "و"}
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
# "400 g" / "1.5 l" / "500 ml" -> "400g" / "1.5l" / "500ml", so a pack size written with a
# space (as price databases do) matches the same size written without one.
_SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|g|mg|ml|cl|l|oz|lb|pcs|pc)\b", re.I)


def _normalize_sizes(text: str) -> str:
    return _SIZE.sub(lambda m: f"{m.group(1).replace(',', '.').replace('.', 'x')}{m.group(2).lower()}", text)


def tokens(text: Optional[str]) -> Set[str]:
    return {t for t in (m.lower() for m in _TOKEN.findall(_normalize_sizes(text or ""))) if len(t) > 1 and t not in _STOP}


def _first_word(text: Optional[str]) -> Optional[str]:
    for match in _TOKEN.finditer(_normalize_sizes(text or "")):
        word = match.group().lower()
        if len(word) > 1 and word not in _STOP:
            return word
    return None


def match_score(product_name: str, listing_title: str) -> float:
    """0-1 share of our name's tokens present in the listing; 0 when any
    digit-bearing token is missing (a different model/size). A listing that
    matches every digit token and our leading word counts as at least
    MIN_SCORE once it has ANCHORED_MIN_SHARE of the words."""
    ours, theirs = tokens(product_name), tokens(listing_title)
    if not ours:
        return 0.0
    digit_tokens = {t for t in ours if any(c.isdigit() for c in t)}
    if digit_tokens - theirs:
        return 0.0
    share = len(ours & theirs) / len(ours)
    if digit_tokens and share >= ANCHORED_MIN_SHARE and _first_word(product_name) in theirs:
        return max(share, MIN_SCORE)
    return share


def is_match(score: float) -> bool:
    return score >= MIN_SCORE


def plausible_price(price: float, reference_price: Optional[float], low: float = 0.2, high: float = 5.0) -> Optional[bool]:
    """Is `price` within [low, high] x our own price (same currency)? None when
    there is nothing to compare against."""
    if not reference_price or reference_price <= 0:
        return None
    return low * reference_price <= price <= high * reference_price


def dedupe_key(provider: str, seller: Optional[str], url: Optional[str], price: float, currency: str) -> str:
    return "|".join((provider, (seller or "").lower(), (url or "").split("#")[0], f"{price:.4f}", currency))


def first_not_none(values: Iterable):
    return next((v for v in values if v is not None), None)
