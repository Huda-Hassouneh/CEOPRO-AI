"""
Everything we know about a product's market and the competitors around it,
beyond the headline competitor price list (dashboard/product_intelligence.py):

- competitor_details(): per competitor - Google rating and review count, the
  real comments collected about it (how many, how many people liked them),
  sentiment (plain, and weighted so a like counts as one more person who
  agrees), social profiles, and how complete its data is and why;
- product_market_detail(): per product - whether it has a market price and from
  what basis (competitor or open-market reference), why not when it has none
  and what to do about it, the reference prices themselves with the listing's
  own star rating and review count, and its barcode.

Read-only; every figure is a stored fact or a count of stored facts.
"""
from typing import Dict, Iterable, Optional

from src.ai.market_inputs import public_sources
from src.ai.sentiment.data_access import load_agreement_weighted_sentiment_by_competitor, load_aggregate_sentiment_by_competitor
from src.market_scraper import price_coverage
from src.market_scraper.competitor_enrichment import load_data_completeness

# Same dead zone around zero dashboard/competitors.py uses for its Positive/Neutral/Negative label.
_SENTIMENT_LABEL_THRESHOLD = 0.1


def sentiment_label(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    if score > _SENTIMENT_LABEL_THRESHOLD:
        return "Positive"
    if score < -_SENTIMENT_LABEL_THRESHOLD:
        return "Negative"
    return "Neutral"


def competitor_details(conn, tenant_id: str, competitor_ids: Optional[Iterable[str]] = None) -> Dict[str, dict]:
    """{competitor_id: details} for this tenant's tracked competitors (or just competitor_ids)."""
    wanted = {str(c) for c in competitor_ids} if competitor_ids is not None else None
    if wanted is not None and not wanted:
        return {}
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT gc.global_competitor_id, gc.rating, gc.rating_count, gc.social_profiles
            FROM tenant_competitors tc JOIN global_competitors gc ON gc.global_competitor_id = tc.global_competitor_id
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE;
            """,
            (tenant_id,),
        )
        base = {str(r[0]): r for r in cursor.fetchall() if wanted is None or str(r[0]) in wanted}
        cursor.execute(
            """
            SELECT competitor_id, COUNT(*), COUNT(*) FILTER (WHERE COALESCE(like_count, 0) > 0)
            FROM reviews
            WHERE tenant_id = %s AND subject_type = 'COMPETITOR' AND competitor_id IS NOT NULL
              AND source_status = 'ALLOWED' AND COALESCE(safety_status, 'SAFE') = 'SAFE'
            GROUP BY competitor_id;
            """,
            (tenant_id,),
        )
        comments = {str(r[0]): (int(r[1]), int(r[2])) for r in cursor.fetchall()}

    sentiment = load_aggregate_sentiment_by_competitor(conn, tenant_id)
    agreement = load_agreement_weighted_sentiment_by_competitor(conn, tenant_id)
    completeness = load_data_completeness(conn, tenant_id)

    details = {}
    for cid, (_id, rating, rating_count, social) in base.items():
        plain = sentiment.get(cid, {}).get("sentiment_score")
        agree = agreement.get(cid, {})
        total, with_likes = comments.get(cid, (0, 0))
        details[cid] = {
            "rating": float(rating) if rating is not None else None,
            "rating_count": rating_count,
            "social_profiles": social or {},
            "comments_collected": total,
            "comments_with_likes": with_likes,
            "people_agreeing": agree.get("people_agreeing"),
            "sentiment_label": sentiment_label(plain),
            "sentiment_score": plain,
            "agreement_weighted_sentiment_score": agree.get("agreement_weighted_score"),
            "data_completeness": completeness.get(cid),
        }
    return details


def _reference_prices(conn, tenant_id: str, product_id: str) -> list:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT seller_name, product_title, source_url, price, currency, rating, review_count,
                   match_score, plausible, provider, observed_at
            FROM market_price_observations WHERE tenant_id = %s AND product_id = %s
            ORDER BY (plausible IS NOT FALSE) DESC, observed_at DESC, price LIMIT 30;
            """,
            (tenant_id, product_id),
        )
        rows = cursor.fetchall()
    return [
        {
            "seller": seller, "listing_title": title,
            "url": public_sources.public_url(public_sources.category(provider), url),
            "price": float(price), "currency": currency,
            "rating": float(rating) if rating is not None else None, "review_count": review_count,
            "match_score": round(score, 2), "counted": plausible is not False,
            "source": public_sources.category(provider), "observed_at": observed_at.isoformat(),
        }
        for seller, title, url, price, currency, rating, review_count, score, plausible, provider, observed_at in rows
    ]


def _reference_market(reference_prices: list, your_price: float, currency: str) -> Optional[dict]:
    """Low / average / high of the counted reference prices in the product's own currency."""
    prices = [p["price"] for p in reference_prices if p["counted"] and p["currency"] == currency]
    if not prices:
        return None
    average = sum(prices) / len(prices)
    return {
        "count": len(prices), "lowest": min(prices), "highest": max(prices), "average": round(average, 4),
        "your_price": your_price,
        "position_pct": round((your_price - average) / average * 100, 1) if average else None,
    }


def product_market_detail(conn, tenant_id: str, product: dict) -> dict:
    product_id = product["product_id"]
    coverage = price_coverage.get_price_coverage(conn, tenant_id, include_covered=True, product_id=product_id)["products"]
    item = coverage[0] if coverage else None
    reference = _reference_prices(conn, tenant_id, product_id)
    with conn.cursor() as cursor:
        cursor.execute("SELECT metadata->>'barcode' FROM products WHERE tenant_id = %s AND product_id = %s;", (tenant_id, product_id))
        row = cursor.fetchone()
    return {
        "barcode": row[0] if row else None,
        "price_coverage": item,
        "reference_prices": reference,
        "reference_market": _reference_market(reference, product["current_price"], product["currency"]),
    }
