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

from src.ai.market_inputs import comment_themes

SORT_HELPFUL = "helpful"   # most people agreeing first
SORT_RECENT = "recent"
SORTS = (SORT_HELPFUL, SORT_RECENT)
SENTIMENTS = ("positive", "negative", "neutral")
ACTION_FILTERS = ("open", "noted", "acted_on")   # open = not handled yet
ACTION_STATUSES = ("noted", "acted_on")
# People who must agree before a comment is worth acting on (a like is one more person who agrees).
SIGNAL_MIN_AGREEING = 3
_VISIBLE = "r.source_status = 'ALLOWED' AND COALESCE(r.safety_status, 'SAFE') = 'SAFE'"


def signal_for(sentiment: Optional[str], agreeing: Optional[int]) -> Optional[str]:
    """What a well-backed comment means for the owner: "opportunity" (customers are unhappy with the
    competitor - a chance to stand out) or "threat" (customers praise it - what you compete against).
    Read from the stored sentiment and likes only; None when it is neutral, unanalysed or lightly backed."""
    if not sentiment or (agreeing or 0) < SIGNAL_MIN_AGREEING:
        return None
    return {"negative": "opportunity", "positive": "threat"}.get(sentiment.lower())


def _comment(row) -> dict:
    review_id, parent_id, platform, author, text, rating, date, likes, replies, sentiment, url, action_status, action_at = row
    return {
        "id": str(review_id), "parent_id": str(parent_id) if parent_id else None, "platform": platform, "author": author,
        "text": text, "rating": float(rating) if rating is not None else None,
        "date": date.isoformat() if date else None,
        "people_agreeing": int(likes) if likes is not None else None,
        "reply_count": int(replies) if replies is not None else None,
        "sentiment": sentiment.lower() if sentiment else None,
        "signal": signal_for(sentiment, likes),
        "url": url,
        "action_status": action_status,
        "action_at": action_at.isoformat() if action_at else None,
        "replies": [],
    }


_COLUMNS = """r.review_id, r.parent_review_id, r.source_platform, r.reviewer_name, r.review_text, r.review_rating,
                   r.review_date, r.like_count, r.reply_count, s.sentiment_label, r.source_url, r.action_status, r.action_at"""
_SENTIMENT_JOIN = "LEFT JOIN sentiment_results s ON s.tenant_id = r.tenant_id AND s.review_id = r.review_id"


def _filters(sentiment, platform, theme, action):
    """(extra WHERE clauses, their arguments) for the optional list filters."""
    clauses, args = [], []
    if sentiment:
        clauses.append("LOWER(s.sentiment_label) = %s")
        args.append(sentiment)
    if platform:
        clauses.append("r.source_platform = %s")
        args.append(platform)
    if theme:
        clauses.append("r.review_text ILIKE ANY(%s)")
        args.append(comment_themes.ilike_patterns(theme))
    if action == "open":
        clauses.append("r.action_status IS NULL")
    elif action:
        clauses.append("r.action_status = %s")
        args.append(action)
    return "".join(f" AND {c}" for c in clauses), tuple(args)


def list_competitor_comments(
    conn, tenant_id: str, competitor_id: str, sort: str = SORT_HELPFUL, limit: int = 20, offset: int = 0,
    sentiment: Optional[str] = None, platform: Optional[str] = None, theme: Optional[str] = None, action: Optional[str] = None,
) -> Optional[dict]:
    """None when this tenant is not tracking that competitor (the caller 404s). The optional filters narrow the
    list (sentiment, platform, theme, action = open | noted | acted_on); `summary` always covers every visible comment."""
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {SORTS}")
    if sentiment is not None and sentiment not in SENTIMENTS:
        raise ValueError(f"sentiment must be one of {SENTIMENTS}")
    if theme is not None and theme not in comment_themes.THEME_KEYS:
        raise ValueError(f"theme must be one of {comment_themes.THEME_KEYS}")
    if action is not None and action not in ACTION_FILTERS:
        raise ValueError(f"action must be one of {ACTION_FILTERS}")
    extra, extra_args = _filters(sentiment, platform, theme, action)
    order = "COALESCE(r.like_count, 0) DESC, r.review_date DESC" if sort == SORT_HELPFUL else "r.review_date DESC"
    mine = "r.tenant_id = %s AND r.subject_type = 'COMPETITOR' AND r.competitor_id = %s"
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
                   COALESCE(SUM(r.like_count), 0),
                   -- the newest of: a comment first stored, or the last successful collection (a refresh that only
                   -- updates likes inserts nothing new but is still a fresh read)
                   GREATEST(MAX(r.created_at), (SELECT MAX(ce.last_attempt_at) FROM competitor_enrichment ce
                            WHERE ce.tenant_id = %s AND ce.global_competitor_id = %s
                              AND ce.facet IN ('COMMENTS', 'REVIEWS') AND ce.status IN ('SUCCEEDED', 'PARTIAL')))
            FROM reviews r WHERE {mine} AND {_VISIBLE};
            """,
            (tenant_id, competitor_id, tenant_id, competitor_id),
        )
        top_level, replies, likes, last_collected = cursor.fetchone()
        cursor.execute(
            f"SELECT r.source_platform, COUNT(*) FROM reviews r WHERE {mine} AND {_VISIBLE} "
            "GROUP BY r.source_platform ORDER BY COUNT(*) DESC;",
            (tenant_id, competitor_id),
        )
        platforms = {name: int(n) for name, n in cursor.fetchall()}
        cursor.execute(
            f"SELECT COUNT(*) FROM reviews r WHERE {mine} AND NOT ({_VISIBLE});",
            (tenant_id, competitor_id),
        )
        held_back = cursor.fetchone()[0]
        cursor.execute(
            f"""
            SELECT LOWER(s.sentiment_label), COUNT(*) FROM reviews r {_SENTIMENT_JOIN}
            WHERE {mine} AND {_VISIBLE} AND r.parent_review_id IS NULL GROUP BY LOWER(s.sentiment_label);
            """,
            (tenant_id, competitor_id),
        )
        by_sentiment = {label: int(n) for label, n in cursor.fetchall()}
        cursor.execute(
            f"""
            SELECT r.review_id, r.review_text, s.sentiment_label, r.like_count FROM reviews r {_SENTIMENT_JOIN}
            WHERE {mine} AND {_VISIBLE} AND r.parent_review_id IS NULL
            ORDER BY COALESCE(r.like_count, 0) DESC, r.review_date DESC LIMIT %s;
            """,
            (tenant_id, competitor_id, comment_themes.MAX_COMMENTS_READ),
        )
        themes = comment_themes.summarise(cursor.fetchall())
        cursor.execute(
            f"SELECT COUNT(*) FROM reviews r {_SENTIMENT_JOIN} WHERE {mine} AND {_VISIBLE} AND r.parent_review_id IS NULL{extra};",
            (tenant_id, competitor_id, *extra_args),
        )
        matching = int(cursor.fetchone()[0])
        cursor.execute(
            f"""
            SELECT {_COLUMNS} FROM reviews r {_SENTIMENT_JOIN}
            WHERE {mine} AND {_VISIBLE} AND r.parent_review_id IS NULL{extra}
            ORDER BY {order} LIMIT %s OFFSET %s;
            """,
            (tenant_id, competitor_id, *extra_args, limit, offset),
        )
        comments = [_comment(row) for row in cursor.fetchall()]
        if comments:
            cursor.execute(
                f"""
                SELECT {_COLUMNS} FROM reviews r {_SENTIMENT_JOIN}
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
            "last_collected_at": last_collected.isoformat() if last_collected else None,
            "sentiment": {
                **{label: by_sentiment.get(label, 0) for label in SENTIMENTS},
                "not_analysed": sum(n for label, n in by_sentiment.items() if label not in SENTIMENTS),
            },
            "themes": themes,
            "matching": matching,
        },
        "comments": comments,
        "next_offset": offset + limit if offset + limit < matching else None,
    }


def set_comment_action(conn, tenant_id: str, competitor_id: str, review_id: str, status: Optional[str], user_id: str) -> Optional[dict]:
    """Records what the owner did about one comment ("noted" / "acted_on"; None clears it). None when the comment
    is not this competitor's, or is held back by the safety scan (an unseen comment cannot be acted on)."""
    if status is not None and status not in ACTION_STATUSES:
        raise ValueError(f"status must be one of {ACTION_STATUSES}")
    with conn.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE reviews r SET action_status = %s, action_by = CASE WHEN %s::text IS NULL THEN NULL ELSE %s::uuid END,
                   action_at = CASE WHEN %s::text IS NULL THEN NULL ELSE NOW() END
            WHERE r.tenant_id = %s AND r.subject_type = 'COMPETITOR' AND r.competitor_id = %s AND r.review_id = %s AND {_VISIBLE}
            RETURNING r.action_status, r.action_at;
            """,
            (status, status, user_id, status, tenant_id, competitor_id, review_id),
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return {"id": review_id, "action_status": row[0], "action_at": row[1].isoformat() if row[1] else None}
