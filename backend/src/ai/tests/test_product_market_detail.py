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

def _comment_row(i, parent=None, likes=5, platform="FACEBOOK", sentiment="NEGATIVE", action=None):
    return (f"r{i}", parent, platform, f"user{i}", f"text {i}", None, NOW, likes, 1, sentiment, f"https://example.com/c/{i}", action, None)


def _comments_cursor(comments, replies=(), platforms=(), sentiments=(), theme_rows=(), counts=(0, 0, 0, None), held=0, matching=None):
    """The queries list_competitor_comments runs, in order: tracked, counts, platforms, held back, sentiment counts,
    theme rows, matching count, the page, and (when the page has comments) its replies."""
    answers = [list(platforms), list(sentiments), list(theme_rows), list(comments)] + ([list(replies)] if comments else [])
    return _one_cursor(fetchone=[(1,), counts, (held,), (len(comments) if matching is None else matching,)], fetchall=answers)


def test_comments_carry_text_likes_replies_and_a_safety_count():
    collected = datetime(2026, 10, 18, tzinfo=timezone.utc)
    conn, _ = _comments_cursor(
        [_comment_row(1, likes=400), _comment_row(2, likes=5)], replies=[_comment_row(9, parent="r1", likes=0, sentiment=None)],
        platforms=[("FACEBOOK", 2), ("GOOGLE", 1)], sentiments=[("negative", 2)], counts=(2, 1, 405, collected), held=3,
        theme_rows=[("r1", "Very slow service", "NEGATIVE", 400)],
    )
    result = cc.list_competitor_comments(conn, "t1", "c1")
    summary = result["summary"]
    assert summary["platforms"] == {"FACEBOOK": 2, "GOOGLE": 1} and summary["held_back_for_safety"] == 3
    assert (summary["comments"], summary["replies"], summary["people_agreeing"]) == (2, 1, 405)
    assert summary["sentiment"] == {"positive": 0, "negative": 2, "neutral": 0, "not_analysed": 0}
    assert summary["last_collected_at"] == collected.isoformat() and summary["matching"] == 2
    assert {t["theme"] for t in summary["themes"]} == {"waiting", "service"}
    first = result["comments"][0]
    assert first["url"] == "https://example.com/c/1" and first["action_status"] is None
    assert first["signal"] == "opportunity" and result["comments"][1]["signal"] == "opportunity"  # negative, 400 and 5 agreeing
    assert first["text"] == "text 1" and first["people_agreeing"] == 400 and first["sentiment"] == "negative"
    assert [r["id"] for r in first["replies"]] == ["r9"] and first["replies"][0]["sentiment"] is None
    assert result["next_offset"] is None


def test_comments_page_and_unknown_competitor_and_bad_filters():
    conn, _ = _comments_cursor([_comment_row(1)], counts=(45, 0, 10, None), matching=45)
    assert cc.list_competitor_comments(conn, "t1", "c1", limit=20, offset=20)["next_offset"] == 40
    conn, _ = _one_cursor(fetchone=[None])
    assert cc.list_competitor_comments(conn, "t1", "nope") is None
    for bad in ({"sort": "loudest"}, {"sentiment": "angry"}, {"theme": "weather"}, {"action": "maybe"}):
        try:
            cc.list_competitor_comments(MagicMock(), "t1", "c1", **bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} must be refused")


def test_filters_narrow_the_list_and_the_paging():
    conn, cursor = _comments_cursor([_comment_row(1)], counts=(30, 0, 0, None), sentiments=[("negative", 25), ("positive", 5)], matching=25)
    result = cc.list_competitor_comments(conn, "t1", "c1", limit=20, sentiment="negative", platform="YouTube", theme="price", action="open")
    count, listing = cursor.execute.call_args_list[6], cursor.execute.call_args_list[7]
    for query in (count.args[0], listing.args[0]):
        assert "LOWER(s.sentiment_label) = %s" in query and "r.source_platform = %s" in query
        assert "ILIKE ANY" in query and "r.action_status IS NULL" in query
    assert listing.args[1][:3] == ("t1", "c1", "negative") and listing.args[1][3] == "YouTube" and listing.args[1][-2:] == (20, 0)
    assert result["next_offset"] == 20  # 25 match, 20 shown
    assert result["summary"]["sentiment"] == {"positive": 5, "negative": 25, "neutral": 0, "not_analysed": 0}


def test_sort_decides_the_order_of_the_comment_query():
    for sort, expected in (("helpful", "COALESCE(r.like_count, 0) DESC"), ("recent", "ORDER BY r.review_date DESC")):
        conn, cursor = _comments_cursor([])
        cc.list_competitor_comments(conn, "t1", "c1", sort=sort)
        listing = cursor.execute.call_args_list[7]
        assert expected in listing.args[0] and listing.args[1][-2:] == (20, 0)