"""How relevant a discovered business is to this company, and how sure we
are that it is a real, open business. Both are 0..1 and come with the
reasons behind them, so the screen can say why a competitor is listed."""
import math
from typing import List, Optional, Tuple

from src.market_scraper.market_discovery import industries
from src.market_scraper.market_discovery.matching import Entity, distance_km
from src.market_scraper.market_discovery.models import DiscoveryQuery

MIN_RELEVANCE = 0.35
_MAP_SOURCES = {"openstreetmap", "overture", "nominatim", "photon", "google_places", "apify_google_maps"}


def industry_fit(entity: Entity, query: DiscoveryQuery) -> Tuple[float, Optional[str]]:
    keys = entity.industry_keys()
    if query.industry_key in keys:
        return 1.0, "same_industry"
    if any(c.raw.get("name_match") for c in entity.candidates):
        return 0.7, "keyword"  # its name says it does what the company does
    if not keys:
        # Web results come from industry searches, so they lean relevant but unproven.
        return (0.6, "keyword") if entity.online_only else (0.45, None)
    industry = industries.get(query.industry_key)
    if industry and any(k in industry.related for k in keys):
        return 0.6, "related_industry"
    return 0.15, "other_industry"


def proximity(entity: Entity, query: DiscoveryQuery) -> Tuple[float, Optional[float]]:
    if not query.has_location or not entity.branches:
        return (0.55 if entity.online_only else 0.4), None
    nearest = None
    for branch in entity.branches:
        branch.distance_km = distance_km(query.latitude, query.longitude, branch.latitude, branch.longitude)
        if branch.distance_km is not None and (nearest is None or branch.distance_km < nearest):
            nearest = branch.distance_km
    if nearest is None:
        return 0.4, None
    radius = max(query.radius_km, 0.5)
    industry = industries.get(query.industry_key)
    if industry and not industry.local:
        return max(0.4, 1 - nearest / (radius * 3)), nearest
    return max(0.0, 1 - (nearest / radius) ** 1.3), nearest


def prominence(entity: Entity) -> float:
    rating, reviews = entity.best_rating()
    score = 0.2
    if reviews:
        score = min(1.0, 0.2 + math.log10(reviews + 1) / 3.5)
    if rating is not None and rating >= 4.3:
        score = min(1.0, score + 0.1)
    score += min(0.15, 0.05 * (len(entity.branches) - 1)) if len(entity.branches) > 1 else 0
    return min(1.0, score)


def confidence(entity: Entity) -> float:
    # The business's own website describes it but isn't an independent
    # listing, so it raises confidence less than a second source does.
    providers = entity.sources - {"website"}
    score = 0.5 if providers & _MAP_SOURCES else 0.3
    score += 0.18 * max(0, len(providers) - 1)
    if "website" in entity.sources:
        score += 0.1
    if entity.first("website"):
        score += 0.08
    if entity.first("phone"):
        score += 0.06
    if entity.first("address"):
        score += 0.04
    _, reviews = entity.best_rating()
    if reviews and reviews >= 10:
        score += 0.08
    return round(min(0.99, score), 4)


def score(entity: Entity, query: DiscoveryQuery) -> Tuple[float, float, Optional[float], List[dict]]:
    """(relevance, confidence, nearest_km, reasons)"""
    fit, fit_reason = industry_fit(entity, query)
    near, nearest = proximity(entity, query)
    relevance = round(min(1.0, 0.5 * fit + 0.32 * near + 0.18 * prominence(entity)), 4)
    if fit_reason == "other_industry":
        relevance = min(relevance, 0.3)
    reasons = []
    if fit_reason:
        reasons.append({"code": fit_reason})
    if nearest is not None:
        reasons.append({"code": "distance", "km": round(nearest, 2)})
    if len(entity.branches) > 1:
        reasons.append({"code": "branches", "count": len(entity.branches)})
    rating, reviews = entity.best_rating()
    if reviews:
        reasons.append({"code": "reviews", "rating": rating, "count": reviews})
    reasons.append({"code": "sources", "count": len(entity.sources)})
    return relevance, confidence(entity), nearest, reasons
