"""Product market detail + competitor details + competitor comments: assembly of stored
facts (DB reads mocked; the SQL itself is covered by the live-DB tests)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from src.ai.dashboard import product_market as pm
from src.ai.market_inputs import competitor_comments as cc

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


def _conn(*fetch_sequences):
    """A connection whose successive cursor() blocks return the given fetchall / fetchone results."""
    conn = MagicMock()
    cursors = []
    for fetchall, fetchone in fetch_sequences:
        cursor = MagicMock()
        cursor.fetchall.return_value = fetchall
        cursor.fetchone.return_value = fetchone
        cursors.append(cursor)
    cm = MagicMock()
    cm.__enter__.side_effect = cursors
    conn.cursor.return_value = cm
    return conn


def _one_cursor(fetchone=(), fetchall=()):
    """A connection whose single cursor answers fetchone()/fetchall() from the given sequences, in call order."""
    cursor = MagicMock()
    cursor.fetchone.side_effect = list(fetchone)
    cursor.fetchall.side_effect = list(fetchall)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_sentiment_label_uses_the_dashboards_dead_zone():
    assert [pm.sentiment_label(v) for v in (0.5, 0.05, -0.05, -0.5, None)] == ["Positive", "Neutral", "Neutral", "Negative", None]


def test_competitor_details_combine_rating_comments_likes_sentiment_and_completeness():
    conn, _ = _one_cursor(fetchall=[[("c1", 4.4, 210, {"instagram": "https://i/x"}), ("c2", None, None, None)], [("c1", 12, 3)]])
    with patch.object(pm, "load_aggregate_sentiment_by_competitor", return_value={"c1": {"sentiment_score": -0.04}}), \
         patch.object(pm, "load_agreement_weighted_sentiment_by_competitor", return_value={"c1": {"agreement_weighted_score": -0.6, "people_agreeing": 412}}), \
         patch.object(pm, "load_data_completeness", return_value={"c1": {"score": 60, "facets": {}}}):
        details = pm.competitor_details(conn, "t1")
    assert details["c1"] == {
        "rating": 4.4, "rating_count": 210, "social_profiles": {"instagram": "https://i/x"},
        "comments_collected": 12, "comments_with_likes": 3, "people_agreeing": 412,
        "sentiment_label": "Neutral", "sentiment_score": -0.04, "agreement_weighted_sentiment_score": -0.6,
        "data_completeness": {"score": 60, "facets": {}},
    }
    # a competitor with nothing collected yet: honest nulls and zeros, nothing invented
    assert details["c2"]["rating"] is None and details["c2"]["comments_collected"] == 0
    assert details["c2"]["sentiment_label"] is None and details["c2"]["people_agreeing"] is None and details["c2"]["data_completeness"] is None


def test_competitor_details_can_be_limited_to_some_ids():
    conn, _ = _one_cursor(fetchall=[[("c1", 4.0, 1, None), ("c2", 3.0, 1, None)], []])
    with patch.object(pm, "load_aggregate_sentiment_by_competitor", return_value={}), \
         patch.object(pm, "load_agreement_weighted_sentiment_by_competitor", return_value={}), \
         patch.object(pm, "load_data_completeness", return_value={}):
        assert set(pm.competitor_details(conn, "t1", ["c2"])) == {"c2"}
    assert pm.competitor_details(MagicMock(), "t1", []) == {}


def test_reference_market_counts_only_counted_prices_in_the_products_currency():
    refs = [
        {"price": 3.0, "currency": "JOD", "counted": True}, {"price": 5.0, "currency": "JOD", "counted": True},
        {"price": 90.0, "currency": "JOD", "counted": False}, {"price": 4.0, "currency": "EUR", "counted": True},
    ]
    market = pm._reference_market(refs, 4.5, "JOD")
    assert market == {"count": 2, "lowest": 3.0, "highest": 5.0, "average": 4.0, "your_price": 4.5, "position_pct": 12.5}
    assert pm._reference_market([], 4.5, "JOD") is None


def test_product_market_detail_assembles_coverage_references_and_barcode():
    conn = _conn(([("Shop", "Nutella 400g", "https://shop.example/p", 3.4, "JOD", 4.6, 128, 1.0, True, "web_offers", NOW)], None), ([], ("3017620422003",)))
    coverage_item = {"product_id": "p1", "has_market_price": True, "price_basis": "market_reference", "reason_code": None}
    with patch.object(pm.price_coverage, "get_price_coverage", return_value={"products": [coverage_item]}) as coverage:
        detail = pm.product_market_detail(conn, "t1", {"product_id": "p1", "current_price": 3.5, "currency": "JOD"})
    assert coverage.call_args.kwargs == {"include_covered": True, "product_id": "p1"}
    assert detail["barcode"] == "3017620422003" and detail["price_coverage"] == coverage_item
    assert detail["reference_prices"][0]["seller"] == "Shop" and detail["reference_prices"][0]["rating"] == 4.6
    assert detail["reference_market"]["count"] == 1 and "web_offers" not in str(detail)  # no vendor names


# ---- comments ---------------------------------------------------------------------------

def _comment_row(i, parent=None, likes=5, platform="FACEBOOK", sentiment="NEGATIVE"):
    return (f"r{i}", parent, platform, f"user{i}", f"text {i}", None, NOW, likes, 1, sentiment)


def test_comments_carry_text_likes_replies_and_a_safety_count():
    conn, _ = _one_cursor(
        fetchone=[(1,), (2, 1, 405), (3,)],
        fetchall=[[("FACEBOOK", 2), ("GOOGLE", 1)], [_comment_row(1, likes=400), _comment_row(2, likes=5)],
                  [_comment_row(9, parent="r1", likes=0, sentiment=None)]],
    )
    result = cc.list_competitor_comments(conn, "t1", "c1")
    assert result["summary"] == {"comments": 2, "replies": 1, "people_agreeing": 405,
                                 "platforms": {"FACEBOOK": 2, "GOOGLE": 1}, "held_back_for_safety": 3}
    first = result["comments"][0]
    assert first["text"] == "text 1" and first["people_agreeing"] == 400 and first["sentiment"] == "negative"
    assert [r["id"] for r in first["replies"]] == ["r9"] and first["replies"][0]["sentiment"] is None
    assert result["next_offset"] is None


def test_comments_page_and_unknown_competitor_and_bad_sort():
    conn, _ = _one_cursor(fetchone=[(1,), (45, 0, 10), (0,)], fetchall=[[], [_comment_row(1)], []])
    assert cc.list_competitor_comments(conn, "t1", "c1", limit=20, offset=20)["next_offset"] == 40
    conn, _ = _one_cursor(fetchone=[None])
    assert cc.list_competitor_comments(conn, "t1", "nope") is None
    try:
        cc.list_competitor_comments(MagicMock(), "t1", "c1", sort="loudest")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown sort must be refused")


def test_sort_decides_the_order_of_the_comment_query():
    for sort, expected in (("helpful", "COALESCE(r.like_count, 0) DESC"), ("recent", "ORDER BY r.review_date DESC")):
        conn, cursor = _one_cursor(fetchone=[(1,), (0, 0, 0), (0,)], fetchall=[[], []])
        cc.list_competitor_comments(conn, "t1", "c1", sort=sort)
        listing = cursor.execute.call_args_list[4]
        assert expected in listing.args[0] and listing.args[1][-2:] == (20, 0)
