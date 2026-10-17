"""
The real comments and reviews collected about one competitor - the text people
wrote, their star rating, how many people liked each one (a like is one more
person who agrees), replies grouped under the comment they answer, and the
sentiment read from the text.

Only comments from approved sources that passed the safety scan are shown;
the number held back is reported, never hidden. Counts and likes are stored
facts, nothing is estimated.
"""
from typing import Optional

SORT_HELPFUL = "helpful"   # most people agreeing first
SORT_RECENT = "recent"
SORTS = (SORT_HELPFUL, SORT_RECENT)
_VISIBLE = "r.source_status = 'ALLOWED' AND COALESCE(r.safety_status, 'SAFE') = 'SAFE'"


def _comment(row) -> dict:
    review_id, parent_id, platform, author, text, rating, date, likes, replies, sentiment = row
    return {
        "id": str(review_id), "parent_id": str(parent_id) if parent_id else None, "platform": platform, "author": author,
        "text": text, "rating": float(rating) if rating is not None else None,
        "date": date.isoformat() if date else None,
        "people_agreeing": int(likes) if likes is not None else None,
        "reply_count": int(replies) if replies is not None else None,
        "sentiment": sentiment.lower() if sentiment else None,
        "replies": [],
    }


def list_competitor_comments(
    conn, tenant_id: str, competitor_id: str, sort: str = SORT_HELPFUL, limit: int = 20, offset: int = 0,
) -> Optional[dict]:
    """None when this tenant is not tracking that competitor (the caller 404s)."""
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {SORTS}")
    order = (
        "COALESCE(r.like_count, 0) DESC, r.review_date DESC" if sort == SORT_HELPFUL else "r.review_date DESC"
    )
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM tenant_competitors WHERE tenant_id = %s AND global_competitor_id = %s AND is_tracked = TRUE;",
            (tenant_id, competitor_id),
        )
        if cursor.fetchone() is None:
            return None
        cursor.execute(
            f"""
            SELECT COUNT(*) FILTER (WHERE r.parent_review_id IS NULL), COUNT(*) FILTER (WHERE r.parent_review_id IS NOT NULL),
                   COALESCE(SUM(r.like_count), 0)
            FROM reviews r
            WHERE r.tenant_id = %s AND r.subject_type = 'COMPETITOR' AND r.competitor_id = %s AND {_VISIBLE};
            """,
            (tenant_id, competitor_id),
        )
        top_level, replies, likes = cursor.fetchone()
        cursor.execute(
            f"""
            SELECT r.source_platform, COUNT(*) FROM reviews r
            WHERE r.tenant_id = %s AND r.subject_type = 'COMPETITOR' AND r.competitor_id = %s AND {_VISIBLE}
            GROUP BY r.source_platform ORDER BY COUNT(*) DESC;
            """,
            (tenant_id, competitor_id),
        )
        platforms = {platform: int(n) for platform, n in cursor.fetchall()}
        cursor.execute(
            "SELECT COUNT(*) FROM reviews r WHERE r.tenant_id = %s AND r.subject_type = 'COMPETITOR' AND r.competitor_id = %s "
            "AND NOT (r.source_status = 'ALLOWED' AND COALESCE(r.safety_status, 'SAFE') = 'SAFE');",
            (tenant_id, competitor_id),
        )
        held_back = cursor.fetchone()[0]
        cursor.execute(
            f"""
            SELECT r.review_id, r.parent_review_id, r.source_platform, r.reviewer_name, r.review_text, r.review_rating,
                   r.review_date, r.like_count, r.reply_count, s.sentiment_label
            FROM reviews r
            LEFT JOIN sentiment_results s ON s.tenant_id = r.tenant_id AND s.review_id = r.review_id
            WHERE r.tenant_id = %s AND r.subject_type = 'COMPETITOR' AND r.competitor_id = %s AND {_VISIBLE}
              AND r.parent_review_id IS NULL
            ORDER BY {order}
            LIMIT %s OFFSET %s;
            """,
            (tenant_id, competitor_id, limit, offset),
        )
        comments = [_comment(row) for row in cursor.fetchall()]
        if comments:
            cursor.execute(
                f"""
                SELECT r.review_id, r.parent_review_id, r.source_platform, r.reviewer_name, r.review_text, r.review_rating,
                       r.review_date, r.like_count, r.reply_count, s.sentiment_label
                FROM reviews r
                LEFT JOIN sentiment_results s ON s.tenant_id = r.tenant_id AND s.review_id = r.review_id
                WHERE r.tenant_id = %s AND r.subject_type = 'COMPETITOR' AND {_VISIBLE}
                  AND r.parent_review_id = ANY(%s::uuid[])
                ORDER BY r.review_date;
                """,
                (tenant_id, [c["id"] for c in comments]),
            )
            by_id = {c["id"]: c for c in comments}
            for row in cursor.fetchall():
                reply = _comment(row)
                if reply["parent_id"] in by_id:
                    by_id[reply["parent_id"]]["replies"].append(reply)

    return {
        "summary": {
            "comments": int(top_level), "replies": int(replies), "people_agreeing": int(likes or 0),
            "platforms": platforms, "held_back_for_safety": int(held_back),
        },
        "comments": comments,
        "next_offset": offset + limit if offset + limit < top_level else None,
    }
