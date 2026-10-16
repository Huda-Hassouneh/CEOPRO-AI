"""
CEOPRO AI - Competitor Confidence Score.

One 0-100 number answering "how sure are we this business really competes
with this tenant", plus the plain-language reasons behind it, so the
competitor list can be ordered best-first and each row can explain itself.

Four honest signals, each 0-100, combined with fixed weights and
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
from dataclasses import dataclass, field
from typing import List, Optional

WEIGHT_CATEGORY = 0.45
WEIGHT_PRODUCTS = 0.30
WEIGHT_PROXIMITY = 0.15
WEIGHT_EVIDENCE = 0.10

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
) -> ConfidenceResult:
    parts = []  # (weight, 0-100 value)
    reasons: List[str] = []

    if category_similarity is not None:
        parts.append((WEIGHT_CATEGORY, category_similarity * 100))
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
        parts.append((WEIGHT_PRODUCTS, value))
        plural = "product" if matched_product_count == 1 else "products"
        reasons.append(f"Sells {matched_product_count} of your {plural} ({product_match_rate:.0%} of your catalog)")
    # No mapped products at all = signal unavailable (a domain-level find),
    # not "sells nothing of yours" - left out rather than scored zero.

    if distance_km is not None:
        parts.append((WEIGHT_PROXIMITY, max(0.0, 1.0 - distance_km / search_radius_km) * 100 if search_radius_km > 0 else 0.0))
        reasons.append(f"{distance_km:.1f} km away")

    evidence_points = sum((has_website, has_address, has_rating))
    parts.append((WEIGHT_EVIDENCE, evidence_points / 3 * 100))

    total_weight = sum(w for w, _ in parts)
    score = round(sum(w * v for w, v in parts) / total_weight, 1) if total_weight else 0.0
    return ConfidenceResult(score=score, label=confidence_label(score), reasons=reasons)
