"""Does a listing's title describe OUR product? Conservative on purpose: a
wrong price is worse than no price, so every digit-bearing token of our name
(model number, size, volume - "dt830b", "500g") must appear in the listing,
and at least MIN_SCORE of all meaningful words must."""
import re
from typing import Iterable, Optional, Set

MIN_SCORE = 0.7
_STOP = {"the", "a", "an", "and", "or", "of", "for", "with", "in", "to", "pack", "new", "من", "في", "مع", "و"}
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def tokens(text: Optional[str]) -> Set[str]:
    return {t for t in (m.lower() for m in _TOKEN.findall(text or "")) if len(t) > 1 and t not in _STOP}


def match_score(product_name: str, listing_title: str) -> float:
    """0-1 share of our name's tokens present in the listing; 0 when any
    digit-bearing token is missing (a different model/size)."""
    ours, theirs = tokens(product_name), tokens(listing_title)
    if not ours:
        return 0.0
    if any(any(c.isdigit() for c in t) and t not in theirs for t in ours):
        return 0.0
    return len(ours & theirs) / len(ours)


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
