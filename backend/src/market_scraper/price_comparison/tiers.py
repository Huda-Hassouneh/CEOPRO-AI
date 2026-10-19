"""
How one of the company's products relates to one item a competitor sells.

  EXACT        the same thing at the same size
  EQUIVALENT   the same thing in a different quantity that scales cleanly:
               a 1-hour class is two 30-minute classes, so the competitor's
               comparable price is twice its listed one
  SIMILAR      the same kind of thing but not like for like: another variant
               (small beef burger vs cheese burger), a nearby quantity (35 vs
               30 minutes, priced pro rata), another size
  ADDED_VALUE  the company's product is the competitor's item plus something
               extra ("extra cheese burger" vs "cheese burger", a class with a
               conversation feature), so a higher price can be justified; the
               comparison shows the premium and whether it is in the usual range

Deterministic and explainable: every result carries the reasons that produced
it. A name that merely shares a word with another ("cheese burger" /
"cheesecake") has no relation at all; nothing is invented to fill a tier.
Prices are compared only by the caller, in one currency.
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional

from src.market_scraper.price_comparison.attributes import Offer, Quantity, contains_word, overlap, reconcile_compounds

EXACT = "EXACT"
EQUIVALENT = "EQUIVALENT"
SIMILAR = "SIMILAR"
ADDED_VALUE = "ADDED_VALUE"
TIERS = (EXACT, EQUIVALENT, SIMILAR, ADDED_VALUE)

OWN_RICHER, OWN_LEANER, SAME = "own_richer", "own_leaner", "same"

# The existing exact matcher's bar (market_discovery/offerings.py MIN_SCORE).
EXACT_MIN_SCORE = 0.75
# Below this the two names have too little in common to be related at all.
RELATED_MIN_SCORE = 0.30
# A comparable price outside this range of the company's own price is a different product class (offerings.PRICE_RATIO).
PRICE_RATIO = (0.2, 5.0)
# A quantity within this of a whole multiple scales cleanly (60 min = 2 x 30 min).
WHOLE_MULTIPLE_TOLERANCE = 0.03
MAX_MULTIPLE = 1000  # 1 kg vs 1 ton; the 0.2x-5x price check below keeps nonsense scalings out
# Quantities further apart than this are not compared at all.
NEAR_QUANTITY_RATIO = (0.25, 4.0)
# Added-value premium (ours over the competitor's base item) that still reads as justified.
PREMIUM_BAND_PCT = float(os.getenv("PRICE_COMPARISON_PREMIUM_BAND_PCT", "60"))
# Charging this much or less over the base item for something extra is under-pricing.
UNDERPRICED_PCT = 2.0

PREMIUM_UNDERPRICED, PREMIUM_WITHIN, PREMIUM_ABOVE = "underpriced", "within_range", "above_range"


@dataclass
class Comparison:
    tier: str
    direction: str
    match_score: float
    scale_factor: float
    comparable_price: float
    price_delta_pct: Optional[float]  # ours vs the comparable price; positive = we are dearer
    reasons: List[dict] = field(default_factory=list)
    premium: Optional[dict] = None
    method: str = "RULES"
    # Set when one name is the other plus extra words that rules cannot place: an addition ("conversation class" =
    # "class" + a feature) or just a variant ("chicken burger"). {"side": "own"|"competitor", "words": [...]}.
    ambiguous: Optional[dict] = None


def _whole_multiple(ratio: float) -> bool:
    big = ratio if ratio >= 1 else 1 / ratio
    nearest = round(big)
    return 2 <= nearest <= MAX_MULTIPLE and abs(big - nearest) <= WHOLE_MULTIPLE_TOLERANCE * nearest


def _quantities(own: Offer, item: Offer):
    """(own quantity, item quantity, unit_assumed). A bare number ("35 class")
    takes the other side's unit; both sides with different dimensions, or one
    side with nothing, are not comparable by quantity."""
    oq, iq, assumed = own.quantity, item.quantity, False
    if oq is None and iq is not None and own.bare_number:
        oq, assumed = Quantity(iq.dimension, own.bare_number * iq.unit_size, f"{own.bare_number:g}", iq.unit_size), True
    elif iq is None and oq is not None and item.bare_number:
        iq, assumed = Quantity(oq.dimension, item.bare_number * oq.unit_size, f"{item.bare_number:g}", oq.unit_size), True
    if oq and iq and oq.dimension == iq.dimension:
        return oq, iq, assumed
    return None, None, assumed


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def premium_for(own_price: float, comparable: float) -> Optional[dict]:
    if comparable <= 0:
        return None
    pct = (own_price - comparable) / comparable * 100
    status = PREMIUM_UNDERPRICED if pct <= UNDERPRICED_PCT else PREMIUM_WITHIN if pct <= PREMIUM_BAND_PCT else PREMIUM_ABOVE
    return {"premium_pct": round(pct, 1), "status": status, "band_pct": PREMIUM_BAND_PCT}


def classify(own: Offer, item: Offer, own_price: float, item_price: float) -> Optional[Comparison]:
    """The relation of `item` (a competitor's) to `own` (the company's), or None when they are unrelated."""
    if not own.words or not item.words or item_price is None or item_price < 0:
        return None
    own, item = reconcile_compounds(own, item)
    score = overlap(own.words, item.words)
    head_shared = bool(own.head and item.head and contains_word(own.head, item.words) and contains_word(item.head, own.words))
    # One name holding every word of the other ("Kunafa" / "Kunafa Nabulsi") is related too: whether the extra word is an
    # extra or only a kind is the ambiguity settled further down.
    contained = (all(contains_word(w, item.words) for w in own.words) or all(contains_word(w, own.words) for w in item.words))
    if score < RELATED_MIN_SCORE or not (head_shared or contained or score >= EXACT_MIN_SCORE):
        return None

    reasons: List[dict] = []
    own_only = [w for w in own.core if not contains_word(w, item.words)]
    item_only = [w for w in item.core if not contains_word(w, own.words)]
    oq, iq, assumed = _quantities(own, item)
    own_nums, item_nums = set(own.numbers), set(item.numbers)
    if assumed:  # a bare number read as the other side's unit ("35 class") is a quantity, not a spec
        used = own.bare_number if own.quantity is None else item.bare_number
        (own_nums if own.quantity is None else item_nums).discard(str(int(used)))
    own_only = own_only + sorted(own_nums - item_nums)  # "SPF 50" / "SPF 30", "iPhone 15" / "iPhone 14", "Taille 38" / "40"
    item_only = item_only + sorted(item_nums - own_nums)
    variant_differs = bool(own_only or item_only)
    if variant_differs:
        reasons.append({"code": "variant_differs", "own": own_only, "competitor": item_only})

    own_more = sorted(own.markers - item.markers) + [w for w in own.withs if not contains_word(w, item.words)]
    item_more = sorted(item.markers - own.markers) + [w for w in item.withs if not contains_word(w, own.words)]
    if own_more:
        reasons.append({"code": "own_has_extras", "extras": own_more})
    if item_more:
        reasons.append({"code": "competitor_has_extras", "extras": item_more})

    size_diff = own.size_or_regular - item.size_or_regular
    if size_diff:
        reasons.append({"code": "size_differs", "own": own.size_or_regular, "competitor": item.size_or_regular})

    quantity_kind, factor = "none", 1.0
    if oq and iq:
        ratio = oq.amount / iq.amount
        if abs(ratio - 1) <= 0.02:
            quantity_kind = "same"
        elif _whole_multiple(ratio) and not assumed:
            quantity_kind, factor = "multiple", ratio
        elif NEAR_QUANTITY_RATIO[0] <= ratio <= NEAR_QUANTITY_RATIO[1]:
            quantity_kind, factor = "near", ratio
        else:
            return None
        if quantity_kind != "same":
            reasons.append({"code": "quantity_scaled" if quantity_kind == "multiple" else "quantity_pro_rata",
                            "factor": round(factor, 4), "own": oq.text, "competitor": iq.text})
        if assumed:
            reasons.append({"code": "quantity_unit_assumed"})
    elif (own.quantity is None) != (item.quantity is None):
        reasons.append({"code": "quantity_not_stated_on_one_side"})

    # One name is the other plus words the rules cannot place (an extra, or only a variant).
    ambiguous = None
    if (own_only or item_only) and not (own_only and item_only) and not own_more and not item_more and not size_diff \
            and quantity_kind in ("none", "same"):
        ambiguous = {"side": "own" if own_only else "competitor", "words": own_only or item_only}
        reasons = [r for r in reasons if r["code"] != "variant_differs"] + [{"code": "specificity_unclear", **ambiguous}]

    # What decides the tier.
    if variant_differs or (own_more and item_more) or quantity_kind == "near" or size_diff:
        tier = SIMILAR
    elif item_more:
        tier = SIMILAR
    elif own_more:
        tier = ADDED_VALUE
    elif quantity_kind == "multiple":
        tier = EQUIVALENT
    else:
        tier = EXACT if score >= EXACT_MIN_SCORE else SIMILAR

    lean = _sign(size_diff) + (_sign(len(own_more) - len(item_more)) if own_more or item_more else 0)
    if quantity_kind == "near":
        lean += _sign(factor - 1)
    direction = OWN_RICHER if lean > 0 else OWN_LEANER if lean < 0 else SAME

    comparable = round(item_price * factor, 4)
    if own_price and comparable and not PRICE_RATIO[0] <= comparable / own_price <= PRICE_RATIO[1]:
        return None
    delta = round((own_price - comparable) / comparable * 100, 1) if comparable > 0 else None
    return Comparison(
        tier=tier, direction=direction, match_score=round(score, 2), scale_factor=round(factor, 4),
        comparable_price=comparable, price_delta_pct=delta, reasons=reasons,
        premium=premium_for(own_price, comparable) if tier == ADDED_VALUE else None, ambiguous=ambiguous,
    )


def apply_verdict(comparison: Comparison, verdict: str, own_price: float, method: str = "AI_ASSISTED") -> Comparison:
    """Settles an ambiguous comparison: verdict "addition" (the extra words are something added) or "variant" (only a
    different kind). Unknown verdicts leave it unsettled."""
    amb = comparison.ambiguous
    if amb is None or verdict not in ("addition", "variant"):
        return comparison
    own_side = amb["side"] == "own"
    reasons = [r for r in comparison.reasons if r["code"] != "specificity_unclear"]
    code = "owner_decision" if method == "OWNER" else "ai_judged"
    reasons.append({"code": code, "verdict": verdict, "side": amb["side"], "words": amb["words"]})
    if verdict == "variant":
        reasons.append({"code": "variant_differs", "own": amb["words"] if own_side else [], "competitor": [] if own_side else amb["words"]})
        tier, direction = SIMILAR, SAME
    elif own_side:
        reasons.append({"code": "own_has_extras", "extras": amb["words"]})
        tier, direction = ADDED_VALUE, OWN_RICHER
    else:
        reasons.append({"code": "competitor_has_extras", "extras": amb["words"]})
        tier, direction = SIMILAR, OWN_LEANER
    return Comparison(
        tier=tier, direction=direction, match_score=comparison.match_score, scale_factor=comparison.scale_factor,
        comparable_price=comparison.comparable_price, price_delta_pct=comparison.price_delta_pct, reasons=reasons,
        premium=premium_for(own_price, comparison.comparable_price) if tier == ADDED_VALUE else None,
        method=method, ambiguous=None,
    )


def force_verdict(comparison: Comparison, verdict: str, own_price: float) -> Comparison:
    """The owner's word, applied to any classified pair (not only ambiguous ones). verdict: "addition" | "variant"."""
    if verdict not in ("addition", "variant"):
        return comparison
    if comparison.ambiguous is not None:
        return apply_verdict(comparison, verdict, own_price, method="OWNER")
    reasons = [r for r in comparison.reasons if r["code"] != "owner_decision"] + [{"code": "owner_decision", "verdict": verdict}]
    if verdict == "addition":
        tier, direction = ADDED_VALUE, OWN_RICHER
    else:
        tier, direction = SIMILAR, SAME
    return Comparison(
        tier=tier, direction=direction, match_score=comparison.match_score, scale_factor=comparison.scale_factor,
        comparable_price=comparison.comparable_price, price_delta_pct=comparison.price_delta_pct, reasons=reasons,
        premium=premium_for(own_price, comparison.comparable_price) if tier == ADDED_VALUE else None, method="OWNER",
    )
