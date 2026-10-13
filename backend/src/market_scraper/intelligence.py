"""Database-backed market scoring, leaderboard, timeline, and expansion opportunities."""

import json

from src.market_scraper.scoring import (
    composite_score,
    expansion_opportunity,
    market_activity,
    price_competitiveness,
    relevance_score,
)


def _metric_rows(conn, tenant_id: str, days: int) -> list[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH latest_prices AS (
                SELECT DISTINCT ON (cp.mapping_id)
                    cp.mapping_id, cp.scraped_price
                FROM competitor_prices cp
                WHERE cp.tenant_id = %s
                  AND cp.source_status = 'ALLOWED'
                  AND cp.is_exact_data = TRUE
                  AND cp.observed_at >= NOW() - (%s * INTERVAL '1 day')
                ORDER BY cp.mapping_id, cp.observed_at DESC
            ), price_metrics AS (
                SELECT cpm.global_competitor_id,
                       AVG(p.current_price)::float AS own_price,
                       AVG(lp.scraped_price)::float AS market_price
                FROM competitor_product_mappings cpm
                JOIN products p ON p.tenant_id = cpm.tenant_id AND p.product_id = cpm.product_id
                LEFT JOIN latest_prices lp ON lp.mapping_id = cpm.mapping_id
                WHERE cpm.tenant_id = %s AND cpm.is_active = TRUE
                GROUP BY cpm.global_competitor_id
            ), sentiment AS (
                SELECT r.competitor_id AS global_competitor_id,
                       AVG((sr.sentiment_score + 1) * 50)::float AS score,
                       COUNT(sr.sentiment_id)::int AS review_count
                FROM reviews r
                LEFT JOIN sentiment_results sr
                  ON sr.tenant_id = r.tenant_id AND sr.review_id = r.review_id
                WHERE r.tenant_id = %s
                  AND r.subject_type = 'COMPETITOR'
                  AND r.source_status = 'ALLOWED'
                  AND r.safety_status = 'SAFE'
                GROUP BY r.competitor_id
            ), activity AS (
                SELECT global_competitor_id, COUNT(*)::int AS event_count
                FROM market_events
                WHERE tenant_id = %s AND occurred_at >= NOW() - (%s * INTERVAL '1 day')
                GROUP BY global_competitor_id
            )
            SELECT tc.global_competitor_id, gc.competitor_name,
                   pm.own_price, pm.market_price, s.score,
                   COALESCE(s.review_count, 0), COALESCE(a.event_count, 0)
            FROM tenant_competitors tc
            JOIN global_competitors gc USING (global_competitor_id)
            LEFT JOIN price_metrics pm USING (global_competitor_id)
            LEFT JOIN sentiment s USING (global_competitor_id)
            LEFT JOIN activity a USING (global_competitor_id)
            WHERE tc.tenant_id = %s AND tc.is_tracked = TRUE;
            """,
            (tenant_id, days, tenant_id, tenant_id, tenant_id, days, tenant_id),
        )
        rows = cursor.fetchall()
    return [
        {
            "global_competitor_id": str(row[0]), "competitor_name": row[1],
            "own_price": row[2], "market_price": row[3], "sentiment": row[4],
            "review_count": row[5], "event_count": row[6],
        }
        for row in rows
    ]


def refresh_score_snapshots(conn, tenant_id: str, days: int = 30) -> list[dict]:
    """Calculate one auditable score snapshot per tracked competitor."""
    snapshots = []
    for metric in _metric_rows(conn, tenant_id, days):
        price = price_competitiveness(metric["own_price"], metric["market_price"])
        activity = market_activity(metric["event_count"], metric["review_count"], days)
        relevance = relevance_score(
            product_similarity=100.0, category_similarity=None, brand_similarity=None,
            price_similarity=price.value, location=None, market_activity=activity,
            customer_sentiment=metric["sentiment"],
        )
        composite = composite_score(price.value, metric["sentiment"], activity)
        missing = sorted(set(price.missing_factors + relevance.missing_factors + composite.missing_factors))
        evidence = {
            "own_average_price": metric["own_price"], "market_average_price": metric["market_price"],
            "review_count": metric["review_count"], "event_count": metric["event_count"],
            "window_days": days,
        }
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO competitor_score_snapshots
                    (tenant_id, global_competitor_id, price_score, sentiment_score,
                     market_activity_score, relevance_score, composite_score,
                     missing_factors, evidence)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                RETURNING score_id, calculated_at;
                """,
                (
                    tenant_id, metric["global_competitor_id"], price.value, metric["sentiment"],
                    activity, relevance.value, composite.value or 0.0,
                    json.dumps(missing), json.dumps(evidence),
                ),
            )
            score_id, calculated_at = cursor.fetchone()
        snapshots.append({
            **metric, "score_id": str(score_id), "calculated_at": calculated_at,
            "price_score_1_to_10": None if price.value is None else price.value / 10,
            "price_score": price.value, "activity_score": activity,
            "relevance_score": relevance.value, "composite_score": composite.value,
            "missing_factors": missing,
        })
    conn.commit()
    return snapshots


def leaderboard(conn, tenant_id: str, limit: int = 20, offset: int = 0) -> list[dict]:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("limit must be 1..100 and offset must be non-negative")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT competitor_name, global_competitor_id, price_score, sentiment_score,
                   market_activity_score, relevance_score, composite_score,
                   missing_factors, calculated_at
            FROM (
                SELECT DISTINCT ON (css.global_competitor_id)
                    gc.competitor_name, css.*
                FROM competitor_score_snapshots css
                JOIN global_competitors gc USING (global_competitor_id)
                WHERE css.tenant_id = %s
                ORDER BY css.global_competitor_id, css.calculated_at DESC
            ) latest
            ORDER BY composite_score DESC, competitor_name
            LIMIT %s OFFSET %s;
            """,
            (tenant_id, limit, offset),
        )
        rows = cursor.fetchall()
    keys = (
        "competitor_name", "global_competitor_id", "price_score", "sentiment_score",
        "market_activity_score", "relevance_score", "composite_score", "missing_factors", "calculated_at",
    )
    return [dict(zip(keys, row)) for row in rows]


def activity_timeline(conn, tenant_id: str, competitor_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("invalid pagination")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT event_id, event_type, old_value, new_value, source_url,
                   occurred_at, collected_at
            FROM market_events
            WHERE tenant_id = %s AND global_competitor_id = %s
            ORDER BY occurred_at DESC LIMIT %s OFFSET %s;
            """,
            (tenant_id, competitor_id, limit, offset),
        )
        rows = cursor.fetchall()
    keys = ("event_id", "event_type", "old_value", "new_value", "source_url", "occurred_at", "collected_at")
    return [dict(zip(keys, row)) for row in rows]


def product_expansion_opportunities(conn, tenant_id: str, limit: int = 10) -> list[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT category, COUNT(*)::int, AVG(rating)::float,
                   COALESCE(SUM(review_count), 0)::int
            FROM market_observations
            WHERE tenant_id = %s AND category IS NOT NULL
              AND safety_status = 'SAFE'
            GROUP BY category ORDER BY COUNT(*) DESC LIMIT %s;
            """,
            (tenant_id, limit),
        )
        rows = cursor.fetchall()
    results = []
    for category, frequency, rating, reviews in rows:
        score = expansion_opportunity(frequency, rating, reviews, None)
        results.append({
            "category": category, "frequency": frequency, "average_rating": rating,
            "review_count": reviews, "opportunity_score": score.value,
            "missing_factors": score.missing_factors,
        })
    return results
