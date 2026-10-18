"""
CEOPRO AI - Competitor Confidence Score.

One 0-100 number answering "how sure are we this business really competes
with this tenant", plus the plain-language reasons behind it, so the
competitor list can be ordered best-first and each row can explain itself.

Four honest signals, each 0-100, combined with configurable weights (see
resolve_weights) and
renormalized over whichever are actually known (an unknown signal is left
out, never counted as zero - same rule scoring.py::composite_score uses):

- category  (45%): category_taxonomy similarity of the two businesses.
- products  (30%): share of the tenant's catalog this competitor also sells,
  scaled so reaching the STRATEGIC match-rate bar scores 100.
- proximity (15%): closer is better, linear to 0 at the search radius.
- evidence  (10%): how much we actually know about them (website, address,
  rating) - a thinly-known business should never outrank a well-evidenced
  one on guesswork alone.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Spec S20: "Weights must be configurable" and ranking "must be transparent
# by default". Defaults below; override per deployment with
# COMPETITOR_CONFIDENCE_WEIGHTS="category=0.45,products=0.30,proximity=0.15,evidence=0.10"
# (any subset; values are renormalized so they need not sum to 1), or per
# call via compute_confidence(weights=...). Every result reports the weights
# it used and each signal's contribution (ConfidenceResult.breakdown).
SIGNALS = ("category", "products", "proximity", "evidence")
DEFAULT_WEIGHTS: Dict[str, float] = {"category": 0.45, "products": 0.30, "proximity": 0.15, "evidence": 0.10}
WEIGHTS_ENV_VAR = "COMPETITOR_CONFIDENCE_WEIGHTS"

DEFAULT_RADIUS_KM = 50.0
HIGH_CONFIDENCE = 70.0
MEDIUM_CONFIDENCE = 45.0

LABEL_HIGH = "High"
LABEL_MEDIUM = "Medium"
LABEL_LOW = "Low"


@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    label: str
    reasons: List[str] = field(default_factory=list)
    # One entry per signal actually used: {"signal", "value" (0-100),
    # "weight" (renormalized over the used signals), "contribution" (points)}.
    breakdown: List[dict] = field(default_factory=list)
    weights: Dict[str, float] = field(default_factory=dict)


def resolve_weights(weights: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Defaults, overridden by the env var, overridden by `weights`. Invalid
    or non-positive entries are ignored (logged), never fatal - a typo in
    config must not take the competitor list down."""
    resolved = dict(DEFAULT_WEIGHTS)
    raw = os.getenv(WEIGHTS_ENV_VAR, "")
    overrides: Dict[str, float] = {}
    for part in raw.split(","):
        if "=" in part:
            key, _, value = part.partition("=")
            try:
                overrides[key.strip()] = float(value)
            except ValueError:
                logger.warning("ignoring invalid %s entry %r", WEIGHTS_ENV_VAR, part)
    overrides.update(weights or {})
    for key, value in overrides.items():
        if key in SIGNALS and value > 0:
            resolved[key] = float(value)
        elif key in SIGNALS and value < 0:
            logger.warning("ignoring non-positive weight for %s", key)
        elif key not in SIGNALS:
            logger.warning("ignoring unknown confidence signal %r", key)
    return resolved


def confidence_label(score: float) -> str:
    if score >= HIGH_CONFIDENCE:
        return LABEL_HIGH
    if score >= MEDIUM_CONFIDENCE:
        return LABEL_MEDIUM
    return LABEL_LOW


def compute_confidence(
    category_similarity: Optional[float],
    product_match_rate: float,
    matched_product_count: int,
    distance_km: Optional[float],
    strategic_match_rate: float,
    has_website: bool = False,
    has_address: bool = False,
    has_rating: bool = False,
    category_label: Optional[str] = None,
    search_radius_km: float = DEFAULT_RADIUS_KM,
    weights: Optional[Dict[str, float]] = None,
) -> ConfidenceResult:
    w = resolve_weights(weights)
    parts = []  # (signal, weight, 0-100 value)
    reasons: List[str] = []

    if category_similarity is not None:
        parts.append(("category", w["category"], category_similarity * 100))
        if category_similarity >= 0.99:
            reasons.append(f"Same business category{f' ({category_label})' if category_label else ''}")
        elif category_similarity >= 0.66:
            reasons.append(f"Closely related category{f' ({category_label})' if category_label else ''}")
        else:
            reasons.append(f"Only broadly related category{f' ({category_label})' if category_label else ''}")
    else:
        reasons.append("Category could not be determined")

    if matched_product_count > 0:
        value = min(product_match_rate / strategic_match_rate, 1.0) * 100 if strategic_match_rate > 0 else 0.0
        parts.append(("products", w["products"], value))
        plural = "product" if matched_product_count == 1 else "products"
        reasons.append(f"Sells {matched_product_count} of your {plural} ({product_match_rate:.0%} of your catalog)")
    # No mapped products at all = signal unavailable (a domain-level find),
    # not "sells nothing of yours" - left out rather than scored zero.

    if distance_km is not None:
        parts.append(("proximity", w["proximity"], max(0.0, 1.0 - distance_km / search_radius_km) * 100 if search_radius_km > 0 else 0.0))
        reasons.append(f"{distance_km:.1f} km away")

    evidence_points = sum((has_website, has_address, has_rating))
    parts.append(("evidence", w["evidence"], evidence_points / 3 * 100))

    total_weight = sum(weight for _, weight, _ in parts)
    breakdown = [
        {
            "signal": signal,
            "value": round(value, 1),
            "weight": round(weight / total_weight, 3),
            "contribution": round(weight / total_weight * value, 1),
        }
        for signal, weight, value in parts
    ] if total_weight else []
    score = round(sum(item["contribution"] for item in breakdown), 1)
    return ConfidenceResult(
        score=score, label=confidence_label(score), reasons=reasons, breakdown=breakdown, weights=w,
    )
