"""Pure market-intelligence scoring functions with explicit missing-data behavior."""

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class ScoreResult:
    value: Optional[float]
    missing_factors: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return asdict(self)


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def price_competitiveness(own_price: Optional[float], market_price: Optional[float]) -> ScoreResult:
    """Return both the dashboard's 1-10 score and its 0-100 equivalent."""
    if own_price is None or market_price is None or own_price <= 0 or market_price <= 0:
        return ScoreResult(None, ("price",))
    difference = abs(own_price - market_price) / market_price
    score_10 = clamp(10.0 - difference * 20.0, 1.0, 10.0)
    return ScoreResult(round(score_10 * 10.0, 2))


def relevance_score(**factors: Optional[float]) -> ScoreResult:
    """Average available 0-100 factors; do not turn unknown factors into zeroes."""
    available = [clamp(float(value)) for value in factors.values() if value is not None]
    missing = tuple(name for name, value in factors.items() if value is None)
    if not available:
        return ScoreResult(None, missing)
    return ScoreResult(round(sum(available) / len(available), 2), missing)


def composite_score(
    price: Optional[float], sentiment: Optional[float], activity: Optional[float]
) -> ScoreResult:
    """Weighted score normalized across only available evidence."""
    weighted = (("price", price, 0.45), ("sentiment", sentiment, 0.35), ("activity", activity, 0.20))
    available = [(clamp(float(value)), weight) for _, value, weight in weighted if value is not None]
    missing = tuple(name for name, value, _ in weighted if value is None)
    if not available:
        return ScoreResult(None, missing)
    total_weight = sum(weight for _, weight in available)
    value = sum(value * weight for value, weight in available) / total_weight
    return ScoreResult(round(value, 2), missing)


def market_activity(event_count: int, review_count: int, days: int = 30) -> float:
    if days <= 0:
        raise ValueError("days must be positive")
    daily_signal = (max(0, event_count) * 2 + max(0, review_count) * 0.25) / days
    return round(clamp(daily_signal * 20.0), 2)


def alert_matches(operator: str, observed: float, threshold: float) -> bool:
    operations = {
        "GT": lambda a, b: a > b,
        "GTE": lambda a, b: a >= b,
        "LT": lambda a, b: a < b,
        "LTE": lambda a, b: a <= b,
    }
    try:
        return operations[operator](observed, threshold)
    except KeyError as exc:
        raise ValueError(f"unsupported alert operator: {operator}") from exc


def expansion_opportunity(frequency: int, rating: Optional[float], reviews: int, relative_price: Optional[float]) -> ScoreResult:
    factors = {
        "frequency": clamp(frequency * 10.0),
        "rating": None if rating is None else clamp(rating / 5.0 * 100.0),
        "reviews": clamp(reviews * 2.0),
        "pricing": None if relative_price is None else clamp(100.0 - abs(relative_price - 1.0) * 100.0),
    }
    return relevance_score(**factors)
