"""
Unit tests for routers/competitor_enrichment.py: data-status, the per-competitor
Retry (synchronous and background) and "retry all failed". DB, Redis and the
enrichment logic are mocked; the logic itself is covered by
market_scraper/tests/test_competitor_enrichment.py.
"""
import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

import redis as redis_lib  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.ai.core.security import create_access_token  # noqa: E402
from src.ai.main import app  # noqa: E402

client = TestClient(app)
COMP = "22222222-2222-2222-2222-222222222222"
R = "src.ai.routers.competitor_enrichment"


def _auth(tenant_id="t1", user_id="u1"):
    token, _ = create_access_token(tenant_id=tenant_id, user_id=user_id)
    return {"Authorization": f"Bearer {token}"}


def test_endpoints_require_auth():
    assert client.get(f"/competitors/{COMP}/data-status").status_code == 401
    assert client.post(f"/competitors/{COMP}/enrich").status_code == 401
    assert client.post("/competitors/enrich-failed").status_code == 401


def test_a_non_uuid_id_is_rejected():
    assert client.get("/competitors/not-a-uuid/data-status", headers=_auth()).status_code == 422
    assert client.post("/competitors/not-a-uuid/enrich", headers=_auth()).status_code == 422


def test_data_status_returns_facets_and_the_queued_flag():
    conn = MagicMock()
    status = {COMP: {"score": 40, "facets": {"PROFILE": {"status": "SUCCEEDED"}}}}
    with patch(f"{R}.db.app_role_connection", return_value=conn) as connect, \
         patch(f"{R}.competitor_enrichment.load_data_completeness", return_value=status) as load, \
         patch(f"{R}._enrichment_redis"), patch(f"{R}.enrichment_queue.is_queued", return_value=True):
        response = client.get(f"/competitors/{COMP}/data-status", headers=_auth())
    assert response.status_code == 200
    assert response.json() == {"competitor_id": COMP, "queued": True, "score": 40, "facets": {"PROFILE": {"status": "SUCCEEDED"}}}
    load.assert_called_once_with(conn, "t1", COMP)
    assert connect.call_args.args[0] == "t1"
    conn.close.assert_called_once()


def test_data_status_is_404_for_a_competitor_the_tenant_does_not_have_and_survives_a_queue_outage():
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.competitor_enrichment.load_data_completeness", return_value={}):
        assert client.get(f"/competitors/{COMP}/data-status", headers=_auth()).status_code == 404
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.competitor_enrichment.load_data_completeness", return_value={COMP: {"score": 0, "facets": {}}}), \
         patch(f"{R}._enrichment_redis"), patch(f"{R}.enrichment_queue.is_queued", side_effect=redis_lib.ConnectionError("down")):
        response = client.get(f"/competitors/{COMP}/data-status", headers=_auth())
    assert response.status_code == 200 and response.json()["queued"] is None


def test_enrich_runs_the_requested_facets_as_the_caller_and_returns_fresh_completeness():
    conn = MagicMock()
    results = {"PROFILE": {"status": "SUCCEEDED"}}
    completeness = {COMP: {"score": 20, "facets": {}}}
    with patch(f"{R}.db.app_role_connection", return_value=conn), \
         patch(f"{R}.competitor_enrichment.enrich_competitor", return_value=results) as enrich, \
         patch(f"{R}.competitor_enrichment.load_data_completeness", return_value=completeness):
        response = client.post(f"/competitors/{COMP}/enrich", json={"facets": ["PROFILE"]}, headers=_auth())
    assert response.status_code == 200
    assert response.json() == {"competitor_id": COMP, "results": results, "data_completeness": completeness[COMP]}
    enrich.assert_called_once_with(conn, "t1", COMP, facets=["PROFILE"], throttle=True, actor_user_id="u1")
    conn.commit.assert_called_once()


def test_enrich_without_a_body_retries_everything_collectable():
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.competitor_enrichment.enrich_competitor", return_value={}) as enrich, \
         patch(f"{R}.competitor_enrichment.load_data_completeness", return_value={}):
        assert client.post(f"/competitors/{COMP}/enrich", headers=_auth()).status_code == 200
    assert enrich.call_args.kwargs["facets"] is None


def test_enrich_rejects_a_facet_that_cannot_be_collected_yet_without_touching_the_database():
    with patch(f"{R}.db.app_role_connection") as connect:
        response = client.post(f"/competitors/{COMP}/enrich", json={"facets": ["NOT_A_FACET"]}, headers=_auth())
    assert response.status_code == 422
    connect.assert_not_called()


def test_enrich_is_404_when_unknown_and_429_when_retried_too_fast():
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.competitor_enrichment.enrich_competitor", side_effect=ValueError("nope")):
        assert client.post(f"/competitors/{COMP}/enrich", headers=_auth()).status_code == 404
    throttled = {"PROFILE": {"status": "THROTTLED", "retry_after_seconds": 12}}
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.competitor_enrichment.enrich_competitor", return_value=throttled):
        response = client.post(f"/competitors/{COMP}/enrich", headers=_auth())
    assert response.status_code == 429 and response.headers["Retry-After"] == "12"


def test_background_retry_queues_a_force_job_and_never_touches_the_database():
    with patch(f"{R}.db.app_role_connection") as connect, patch(f"{R}._enrichment_redis"), \
         patch(f"{R}.enrichment_queue.enqueue_enrichment", return_value="1-0") as enqueue:
        response = client.post(f"/competitors/{COMP}/enrich?background=true", json={"facets": ["PROFILE"]}, headers=_auth())
    assert response.status_code == 202
    assert response.json() == {"queued": True, "already_queued": False, "competitor_id": COMP, "mode": "force"}
    assert enqueue.call_args.args[1:] == ("t1", COMP, ["PROFILE"], "force")
    connect.assert_not_called()


def test_background_retry_reports_a_duplicate_and_is_503_when_the_queue_is_down():
    with patch(f"{R}._enrichment_redis"), patch(f"{R}.enrichment_queue.enqueue_enrichment", return_value=None):
        response = client.post(f"/competitors/{COMP}/enrich?background=true", headers=_auth())
    assert response.status_code == 202 and response.json()["already_queued"] is True
    with patch(f"{R}._enrichment_redis"), \
         patch(f"{R}.enrichment_queue.enqueue_enrichment", side_effect=redis_lib.ConnectionError("down")):
        assert client.post(f"/competitors/{COMP}/enrich?background=true", headers=_auth()).status_code == 503


def test_retry_all_failed_queues_one_tenant_wide_force_job():
    with patch(f"{R}._enrichment_redis"), patch(f"{R}.enrichment_queue.enqueue_enrichment", return_value="2-0") as enqueue:
        response = client.post("/competitors/enrich-failed", headers=_auth())
    assert response.status_code == 202 and response.json()["competitor_id"] is None
    assert enqueue.call_args.args[1:] == ("t1", None, None, "force")


def test_market_coverage_requires_auth_and_returns_the_report_for_the_callers_tenant():
    assert client.get("/pricing/market-coverage").status_code == 401
    conn = MagicMock()
    report = {"summary": {"total_products": 0}, "products": []}
    with patch(f"{R}.db.app_role_connection", return_value=conn) as connect, \
         patch(f"{R}.price_coverage.get_price_coverage", return_value=report) as coverage:
        response = client.get("/pricing/market-coverage?include_covered=true&limit=10&offset=5", headers=_auth())
    assert response.status_code == 200 and response.json() == report
    coverage.assert_called_once_with(conn, "t1", True, 10, 5, False)
    assert connect.call_args.args[0] == "t1"
    assert client.get("/pricing/market-coverage?limit=0", headers=_auth()).status_code == 422


def test_fill_market_price_gaps_queues_a_tenant_wide_prices_job():
    assert client.post("/pricing/market-coverage/fill").status_code == 401
    with patch(f"{R}._enrichment_redis"), patch(f"{R}.enrichment_queue.enqueue_enrichment", return_value="9-0") as enqueue:
        response = client.post("/pricing/market-coverage/fill", headers=_auth())
    assert response.status_code == 202 and response.json()["mode"] == "prices"
    assert enqueue.call_args.args[1:] == ("t1", None, None, "prices")


def test_market_prices_lists_a_products_reference_prices_without_naming_the_vendor():
    from datetime import datetime, timezone
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = [(
        "Shop", "Nutella 350g", "https://shop.example/p", 3.4, "JOD", 4.6, 128, 1.0, True, "serpapi_shopping",
        datetime(2026, 10, 18, tzinfo=timezone.utc),
    ), ("Far", "Nutella", None, 90, "JOD", None, None, 0.9, False, "web_offers", datetime(2026, 10, 18, tzinfo=timezone.utc))]
    with patch(f"{R}.db.app_role_connection", return_value=conn):
        response = client.get(f"/pricing/market-prices/{COMP}", headers=_auth())
    assert response.status_code == 200
    prices = response.json()["prices"]
    assert prices[0]["seller"] == "Shop" and prices[0]["rating"] == 4.6 and prices[0]["review_count"] == 128 and prices[0]["counted"] is True
    assert prices[1]["counted"] is False
    assert "serpapi" not in json.dumps(response.json()).lower()


def test_market_prices_is_404_for_an_unknown_product_and_422_for_a_bad_id():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    with patch(f"{R}.db.app_role_connection", return_value=conn):
        assert client.get(f"/pricing/market-prices/{COMP}", headers=_auth()).status_code == 404
    assert client.get("/pricing/market-prices/nope", headers=_auth()).status_code == 422


def test_market_coverage_can_list_the_missing_barcode_worklist():
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.price_coverage.get_price_coverage", return_value={"summary": {}, "products": []}) as coverage:
        assert client.get("/pricing/market-coverage?missing_barcode=true", headers=_auth()).status_code == 200
    assert coverage.call_args.args[-1] is True


def test_competitor_reviews_endpoint_returns_comments_and_validates_input():
    assert client.get(f"/competitors/{COMP}/reviews").status_code == 401
    assert client.get("/competitors/nope/reviews", headers=_auth()).status_code == 422
    assert client.get(f"/competitors/{COMP}/reviews?sort=loudest", headers=_auth()).status_code == 422
    assert client.get(f"/competitors/{COMP}/reviews?limit=0", headers=_auth()).status_code == 422
    result = {"summary": {"comments": 1}, "comments": [{"id": "r1", "text": "Awful", "people_agreeing": 400}], "next_offset": None}
    conn = MagicMock()
    with patch(f"{R}.db.app_role_connection", return_value=conn), \
         patch(f"{R}.competitor_comments.list_competitor_comments", return_value=result) as listing:
        response = client.get(f"/competitors/{COMP}/reviews?sort=recent&limit=5&offset=10", headers=_auth())
    assert response.status_code == 200 and response.json() == {"competitor_id": COMP, **result}
    listing.assert_called_once_with(conn, "t1", COMP, "recent", 5, 10)


def test_competitor_reviews_is_404_for_a_competitor_the_tenant_does_not_track():
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.competitor_comments.list_competitor_comments", return_value=None):
        assert client.get(f"/competitors/{COMP}/reviews", headers=_auth()).status_code == 404


def test_competitor_data_overview_is_one_bulk_read_for_the_callers_tenant():
    assert client.get("/competitor-data/overview").status_code == 401
    conn = MagicMock()
    with patch(f"{R}.db.app_role_connection", return_value=conn) as connect, \
         patch(f"{R}.product_market.competitor_details", return_value={COMP: {"rating": 4.4}}) as details:
        response = client.get("/competitor-data/overview", headers=_auth())
    assert response.status_code == 200 and response.json() == {"competitors": {COMP: {"rating": 4.4}}}
    details.assert_called_once_with(conn, "t1")
    assert connect.call_args.args[0] == "t1"


def test_deep_retry_is_passed_to_the_collector_and_the_queue():
    # A standard synchronous retry still reaches the collector; a deep one is queued with its depth.
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.competitor_enrichment.enrich_competitor", return_value={}) as enrich, \
         patch(f"{R}.competitor_enrichment.load_data_completeness", return_value={}):
        assert client.post(f"/competitors/{COMP}/enrich", json={"facets": ["PRICES"]}, headers=_auth()).status_code == 200
    assert "deep" not in enrich.call_args.kwargs and enrich.call_args.kwargs["facets"] == ["PRICES"]
    with patch(f"{R}._enrichment_redis"), patch(f"{R}.enrichment_queue.enqueue_enrichment", return_value="3-0") as enqueue:
        assert client.post(f"/competitors/{COMP}/enrich?background=true", json={"facets": ["PRICES"], "depth": "deep"},
                           headers=_auth()).status_code == 202
    assert enqueue.call_args.args[-1] == "deep"
    assert client.post(f"/competitors/{COMP}/enrich", json={"depth": "everything"}, headers=_auth()).status_code == 422


def test_a_deep_read_is_always_queued_even_when_the_caller_did_not_ask_for_background():
    with patch(f"{R}._enrichment_redis"), patch(f"{R}.enrichment_queue.enqueue_enrichment", return_value="4-0") as enqueue, \
         patch(f"{R}.competitor_enrichment.enrich_competitor") as direct:
        response = client.post(f"/competitors/{COMP}/enrich", json={"facets": ["PRICES"], "depth": "deep"}, headers=_auth())
    assert response.status_code == 202 and response.json()["queued"] is True
    direct.assert_not_called()  # nothing ran inside the request
    assert enqueue.call_args.args[-1] == "deep"


def test_the_overview_can_be_limited_to_the_competitors_on_screen():
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.product_market.competitor_details", return_value={COMP: {"rating": 4.4}}) as details:
        assert client.get("/competitor-data/overview", headers=_auth()).json() == {"competitors": {COMP: {"rating": 4.4}}}
        assert len(details.call_args.args) == 2  # no ids: every tracked competitor, exactly as before
        client.get(f"/competitor-data/overview?ids={COMP}, {COMP}", headers=_auth())
        assert details.call_args.args[2] == [COMP, COMP]
        assert client.get("/competitor-data/overview?ids=not-a-uuid", headers=_auth()).status_code == 422
        too_many = ",".join([COMP] * 201)
        assert client.get(f"/competitor-data/overview?ids={too_many}", headers=_auth()).status_code == 422
