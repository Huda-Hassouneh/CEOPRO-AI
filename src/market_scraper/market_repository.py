"""Atomic persistence for observations, prices, reviews, events, and alert triggers."""

import json
from decimal import Decimal

from src.market_scraper.scoring import alert_matches
from src.market_scraper.staging import content_hash as _content_hash

METHOD_TO_REVIEW_METHOD = {
    "OFFICIAL_API": "PUBLIC_API",
    "RSS": "PUBLIC_FEED",
    "STRUCTURED_DATA": "STRUCTURED_DATA",
    "WEB_SCRAPE": "WEB_SCRAPE",
}


def _previous_observation(cursor, item: dict):
    cursor.execute(
        """
        SELECT cp.scraped_price, cp.is_available, cp.observed_at
        FROM competitor_prices cp
        WHERE cp.tenant_id = %s AND cp.mapping_id = %s
        ORDER BY cp.observed_at DESC LIMIT 1;
        """,
        (item["tenant_id"], item["mapping_id"]),
    )
    return cursor.fetchone()


def _insert_event(cursor, item: dict, event_type: str, old_value, new_value) -> str:
    cursor.execute(
        """
        INSERT INTO market_events
            (tenant_id, global_competitor_id, mapping_id, source_id, event_type,
             old_value, new_value, source_url, occurred_at)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
        RETURNING event_id;
        """,
        (
            item["tenant_id"], item["global_competitor_id"], item["mapping_id"], item["source_id"],
            event_type, json.dumps(old_value) if old_value is not None else None,
            json.dumps(new_value), item["product_url"], item["captured_at"],
        ),
    )
    return str(cursor.fetchone()[0])


def _trigger_price_alerts(cursor, item: dict, event_id: str, old_price: Decimal):
    new_price = Decimal(str(item["price_amount"]))
    if old_price == 0:
        return
    change_percent = (new_price - old_price) / old_price * 100
    cursor.execute(
        """
        SELECT alert_rule_id, operator, threshold
        FROM market_alert_rules
        WHERE tenant_id = %s AND global_competitor_id = %s
          AND metric = 'PRICE_CHANGE_PERCENT' AND is_active = TRUE;
        """,
        (item["tenant_id"], item["global_competitor_id"]),
    )
    for rule_id, operator, threshold in cursor.fetchall():
        if alert_matches(operator, float(change_percent), float(threshold)):
            cursor.execute(
                """
                INSERT INTO market_alert_events
                    (tenant_id, alert_rule_id, market_event_id, observed_value, message)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (
                    item["tenant_id"], rule_id, event_id, change_percent,
                    f"{item['competitor_name']} price changed {change_percent:.2f}% for {item['product_name']}",
                ),
            )


def save_market_record(conn, item: dict) -> dict:
    """Promote one safe staged item atomically; quarantine unsafe text without prices."""
    staging_id = item.get("_staging_id")
    if not staging_id:
        raise ValueError("mapped records must pass through Tier-2 staging")
    if item.get("safety_status") == "QUARANTINED":
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE market_observation_staging
                SET validation_status = 'QUARANTINED', resolved_at = NOW()
                WHERE tenant_id = %s AND staging_id = %s;
                """,
                (item["tenant_id"], staging_id),
            )
        conn.commit()
        return {
            "status": "QUARANTINED", "price_id": None, "observation_id": None,
            "review_ids": [], "event_ids": [],
        }
    has_price = item.get("price_amount") is not None
    with conn.cursor() as cursor:
        previous = _previous_observation(cursor, item) if has_price else None
        price_id = None
        if has_price:
            cursor.execute(
                """
                INSERT INTO competitor_prices
                    (tenant_id, mapping_id, scraped_price, currency, is_available,
                     observed_at, source_status, is_exact_data)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING competitor_price_id;
                """,
                (
                    item["tenant_id"], item["mapping_id"], item["price_amount"], item["currency"],
                    item["is_available"], item["captured_at"], item["source_status"], item["is_exact_data"],
                ),
            )
            price_id = str(cursor.fetchone()[0])
        cursor.execute(
            """
            INSERT INTO market_observations
                (tenant_id, source_id, job_id, mapping_id, product_name, category, description,
                 canonical_url, image_url, external_id, rating, review_count, stock_quantity,
                 match_score, match_method, page_text, safety_status, safety_flags,
                 content_hash, raw_payload, observed_at,
                 product_id, global_competitor_id, source_platform, country_code,
                 price_amount, currency, is_available, published_at,
                 author_name, author_handle, likes_count, comments_count, shares_count, views_count,
                 engagement_captured_at, hashtags, mentions, media_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s::jsonb, %s::jsonb, %s)
            RETURNING observation_id;
            """,
            (
                item["tenant_id"], item["source_id"], item["job_id"], item["mapping_id"],
                item["product_name"], item.get("category"), item.get("description"), item["product_url"],
                item.get("image_url"), item.get("external_id"), item.get("rating"), item.get("review_count"),
                item.get("stock_quantity"), item["match_score"], item["match_method"],
                item.get("page_text"), item.get("safety_status", "SAFE"),
                json.dumps(item.get("safety_flags", [])), _content_hash(item),
                json.dumps(
                    {key: value for key, value in dict(item).items() if not key.startswith("_")},
                    default=str,
                ),
                item["captured_at"],
                # Comprehensive market-data-record fields (spec: search by
                # product and competitor, capture all available engagement/
                # market signals) - all read via .get() with a None default
                # so a spider that doesn't have a given signal (e.g. Amazon
                # PA-API has no "likes") simply stores NULL, never breaks.
                item.get("product_id"), item.get("global_competitor_id"),
                item.get("source_platform"), item.get("country_code"),
                item.get("price_amount"), item.get("currency"), item.get("is_available"),
                item.get("published_at"),
                item.get("author_name"), item.get("author_handle"),
                item.get("likes_count"), item.get("comments_count"),
                item.get("shares_count"), item.get("views_count"),
                item.get("engagement_captured_at"),
                json.dumps(item.get("hashtags") or []), json.dumps(item.get("mentions") or []),
                item.get("media_type"),
            ),
        )
        observation_id = str(cursor.fetchone()[0])
        review_ids = _save_reviews(cursor, item)
        event_ids = _derive_events(cursor, item, previous) if has_price else []
        cursor.execute(
            """
            UPDATE market_observation_staging
            SET validation_status = 'PROMOTED', resolved_at = NOW()
            WHERE tenant_id = %s AND staging_id = %s;
            """,
            (item["tenant_id"], staging_id),
        )
    conn.commit()
    return {
        "status": "PROMOTED", "price_id": price_id,
        "observation_id": observation_id, "review_ids": review_ids,
        "event_ids": event_ids,
    }


def _save_reviews(cursor, item: dict) -> list[str]:
    review_ids = []
    method = METHOD_TO_REVIEW_METHOD[item["collection_method"]]
    for review in item.get("reviews") or []:
        cursor.execute(
            """
            INSERT INTO reviews
                (tenant_id, product_id, source_platform, reviewer_name, review_text, review_rating,
                 review_date, subject_type, competitor_id, source_status, collection_method,
                 source_id, external_review_id, safety_status, safety_flags)
            VALUES (%s, NULL, %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()),
                    'COMPETITOR', %s, 'ALLOWED', %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (tenant_id, source_id, external_review_id)
                WHERE source_id IS NOT NULL AND external_review_id IS NOT NULL
            DO UPDATE SET review_text = EXCLUDED.review_text,
                          review_rating = EXCLUDED.review_rating,
                          review_date = EXCLUDED.review_date
            RETURNING review_id;
            """,
            (
                item["tenant_id"], item["source_name"], review.get("reviewer_name"), review["review_text"],
                review.get("review_rating"), review.get("review_date"), item["global_competitor_id"],
                method, item["source_id"], review["external_review_id"],
                review.get("safety_status", "SAFE"), json.dumps(review.get("safety_flags", [])),
            ),
        )
        review_ids.append(str(cursor.fetchone()[0]))
    return review_ids


def _derive_events(cursor, item: dict, previous) -> list[str]:
    if previous is None:
        return [_insert_event(cursor, item, "PRODUCT_DISCOVERED", None, {"price": item["price_amount"], "currency": item["currency"]})]
    old_price, old_available, _ = previous
    events = []
    if Decimal(str(old_price)) != Decimal(str(item["price_amount"])):
        event_id = _insert_event(
            cursor, item, "PRICE_CHANGED", {"price": float(old_price)},
            {"price": float(item["price_amount"]), "currency": item["currency"]},
        )
        _trigger_price_alerts(cursor, item, event_id, Decimal(str(old_price)))
        events.append(event_id)
    if bool(old_available) != bool(item["is_available"]):
        events.append(_insert_event(cursor, item, "AVAILABILITY_CHANGED", {"available": old_available}, {"available": item["is_available"]}))
    return events
