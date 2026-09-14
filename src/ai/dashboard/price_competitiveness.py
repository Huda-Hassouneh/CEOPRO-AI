"""
CEOPRO AI - Dashboard Price Competitiveness Score (presentation layer, not
a new model).

The mockup's "Price Competitiveness 7.8/10" card. Reuses market_scraper/
scoring.py::price_competitiveness() - a pure, already-existing, already-
tested 1-10 scoring function (10 = priced right at the market, dropping
as your price diverges either direction) - over the exact same "your
price vs. most recent competitor observation, per product" data
competitor_pricing.py already reads, just averaged into one headline
number instead of returned per-product. No new scoring rule invented
here, no new table: this is the same building block used twice.
"""
from src.market_scraper.scoring import price_competitiveness

DEFAULT_TREND_WINDOW_DAYS = 30


def _load_price_pairs(conn, tenant_id: str, before=None) -> list:
    """(your_price, most-recent-competitor-price-as-of `before`) per
    product with at least one real competitor observation. `before`
    (optional) restricts to the most recent observation BEFORE that
    timestamp - used to compute a prior-period score for the trend,
    without needing a second table or a stored snapshot."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.current_price, latest.scraped_price
            FROM products p
            JOIN competitor_product_mappings cpm ON cpm.tenant_id = p.tenant_id AND cpm.product_id = p.product_id
            JOIN LATERAL (
                SELECT cpr.scraped_price
                FROM competitor_prices cpr
                WHERE cpr.tenant_id = cpm.tenant_id AND cpr.mapping_id = cpm.mapping_id
                  AND (%(before)s::timestamptz IS NULL OR cpr.observed_at < %(before)s)
                ORDER BY cpr.observed_at DESC
                LIMIT 1
            ) latest ON TRUE
            WHERE p.tenant_id = %(tenant_id)s AND p.deleted_at IS NULL;
            """,
            {"tenant_id": tenant_id, "before": before},
        )
        return cursor.fetchall()


def _average_score(pairs: list):
    scores = [
        price_competitiveness(float(own), float(market)).value
        for own, market in pairs
    ]
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores) / 10, 2)  # scoring.py's own_price=0-100 scale -> this card's 0-10 scale


def get_price_competitiveness(conn, tenant_id: str, trend_window_days: int = DEFAULT_TREND_WINDOW_DAYS) -> dict:
    from datetime import datetime, timedelta, timezone

    current_score = _average_score(_load_price_pairs(conn, tenant_id))
    if current_score is None:
        return {"score": None, "change": None}

    prior_cutoff = datetime.now(timezone.utc) - timedelta(days=trend_window_days)
    prior_score = _average_score(_load_price_pairs(conn, tenant_id, before=prior_cutoff))

    return {
        "score": current_score,
        "change": round(current_score - prior_score, 2) if prior_score is not None else None,
    }
