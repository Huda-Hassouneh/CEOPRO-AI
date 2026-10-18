"""A like is one more person agreeing: agreement-weighted sentiment, as an
addition to (never a replacement for) the plain sentiment score."""
from unittest.mock import MagicMock

from src.ai.sentiment.data_access import load_agreement_weighted_sentiment_by_competitor


def _conn(rows):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = rows
    return conn


def test_returns_score_and_people_agreeing_per_competitor():
    conn = _conn([("c1", -0.61234, 412, 3), ("c2", None, None, None)])
    result = load_agreement_weighted_sentiment_by_competitor(conn, "t1")
    assert result == {
        "c1": {"agreement_weighted_score": -0.6123, "people_agreeing": 412, "comments_with_likes": 3},
        "c2": {"agreement_weighted_score": None, "people_agreeing": 0, "comments_with_likes": 0},
    }


def test_query_weights_each_comment_by_one_plus_its_likes_and_is_tenant_scoped():
    conn = _conn([])
    assert load_agreement_weighted_sentiment_by_competitor(conn, "t1") == {}
    cursor = conn.cursor.return_value.__enter__.return_value
    sql, params = cursor.execute.call_args.args
    assert "1 + COALESCE(r.like_count, 0)" in sql and "r.tenant_id = %s" in sql
    assert params == ("t1",)
