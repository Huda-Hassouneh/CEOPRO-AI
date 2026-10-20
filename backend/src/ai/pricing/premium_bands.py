"""
KEEL - Premium bands per category, and price guidance for added-value products.

An ADDED_VALUE comparison says "your product is a competitor's base item plus something extra". How much more may
that justify? One global band (PRICE_COMPARISON_PREMIUM_BAND_PCT, default 60 %) is a guess; this module replaces it,
per category, with what the market in this company's own data shows: the premiums that competitors-vs-you pairs in the
same category carry, taken at their 75th percentile. Not learned from recommendation outcomes: that table records only
whether an owner accepted a suggestion, not what happened to sales (pricing/recommendation.py, spec S19 keeps learned
pricing off until real history exists).

  * fewer than MIN_SAMPLES pairs in a category -> the default band, labelled "default"
  * otherwise the 75th percentile of the positive premiums, kept inside [MIN_BAND_PCT, MAX_BAND_PCT], labelled "observed"
    with its sample size

Guidance never produces a price: for a product that only has added-value comparisons it gives the range its price would
read as justified in, and where the current price sits against it.
"""
import statistics
from typing import Dict, Iterable, List, Optional

from src.market_scraper.price_comparison import tiers

MIN_SAMPLES = 5
MIN_BAND_PCT, MAX_BAND_PCT = 20.0, 150.0
DEFAULT_SOURCE, OBSERVED_SOURCE, OWNER_SOURCE = "default", "observed", "owner"
UNCATEGORISED = "__none__"


def derive_band(premiums: Iterable[float], default: float = None) -> dict:
    default = tiers.PREMIUM_BAND_PCT if default is None else default
    positive = sorted(p for p in premiums if p is not None and p > tiers.UNDERPRICED_PCT)
    if len(positive) < MIN_SAMPLES:
        return {"band_pct": default, "source": DEFAULT_SOURCE, "samples": len(positive)}
    p75 = statistics.quantiles(positive, n=4, method="inclusive")[2]
    return {"band_pct": round(min(max(p75, MIN_BAND_PCT), MAX_BAND_PCT), 1), "source": OBSERVED_SOURCE, "samples": len(positive)}


def default_band() -> dict:
    return {"band_pct": tiers.PREMIUM_BAND_PCT, "source": DEFAULT_SOURCE, "samples": 0}


def status_for(premium_pct: float, band_pct: float) -> str:
    if premium_pct <= tiers.UNDERPRICED_PCT:
        return tiers.PREMIUM_UNDERPRICED
    return tiers.PREMIUM_WITHIN if premium_pct <= band_pct else tiers.PREMIUM_ABOVE


def apply_band(premium: Optional[dict], band: dict) -> Optional[dict]:
    """The stored premium re-read against a category band (the stored status used the global default)."""
    if not premium or premium.get("premium_pct") is None:
        return premium
    return {**premium, "status": status_for(premium["premium_pct"], band["band_pct"]), "band_pct": band["band_pct"],
            "band_source": band["source"], "band_samples": band["samples"]}


def guidance(your_price: float, added_value_items: List[dict], band: dict) -> Optional[dict]:
    """The range your price reads as justified in, from the competitors' base items. None without such items."""
    prices = [i["comparable_price"] for i in added_value_items if i.get("comparable_price")]
    if not prices or not your_price:
        return None
    base = statistics.median(prices)
    low = round(base * (1 + tiers.UNDERPRICED_PCT / 100), 4)
    high = round(base * (1 + band["band_pct"] / 100), 4)
    position = "below_range" if your_price <= low else "within_range" if your_price <= high else "above_range"
    return {
        "kind": "range_not_a_price", "base_price": round(base, 4), "base_items": len(prices), "range_low": low, "range_high": high,
        "band_pct": band["band_pct"], "band_source": band["source"], "band_samples": band["samples"],
        "your_price": your_price, "position": position,
        "your_premium_pct": round((your_price - base) / base * 100, 1) if base else None,
    }


def guidance_sentence(g: dict, money) -> str:
    where = {"below_range": "at or below the bottom of that range (you may be under-pricing the extra)",
             "within_range": "inside that range",
             "above_range": "above that range (the extra may be priced beyond what the market usually supports)"}[g["position"]]
    basis = ("the band you set" if g["band_source"] == OWNER_SOURCE else f"the usual premium for this category from {g['band_samples']} comparisons" if g["band_source"] == OBSERVED_SOURCE
             else "a default premium band (not enough comparisons in this category yet)")
    return (f"Added-value guidance (not a market price, and not averaged into the figures above): competitors sell the base "
            f"item at about {money(g['base_price'])}; with the extra, {money(g['range_low'])} to {money(g['range_high'])} reads as "
            f"justified, using {basis} of up to +{g['band_pct']:.0f}%. Your price is {where}.")
