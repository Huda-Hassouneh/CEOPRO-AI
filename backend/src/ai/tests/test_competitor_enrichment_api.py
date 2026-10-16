"""
Unit tests for routers/competitor_enrichment.py: data-status, the per-competitor
Retry (synchronous and background) and "retry all failed". DB, Redis and the
enrichment logic are mocked; the logic itself is covered by
market_scraper/tests/test_competitor_enrichment.py.
"""
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
        response = client.post(f"/competitors/{COMP}/enrich", json={"facets": ["PRICES"]}, headers=_auth())
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
