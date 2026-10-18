"""
Unit tests for the two new routers/competitors.py endpoints - GET
/competitors/sources and POST /competitors/sources/{source_id}/review -
the product-facing entry point for source_review.py's human-in-the-loop
policy review. Same convention as test_settings.py: DB calls mocked
(db.app_role_connection replaced with a MagicMock connection, plus the
router's own helper functions where that's the simpler/more faithful
mock), real JWT auth exercised for real via a real access token.
"""
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.ai.core.security import create_access_token  # noqa: E402
from src.ai.main import app  # noqa: E402

client = TestClient(app)


def _fake_conn():
    conn = MagicMock()
    conn.close = MagicMock()
    return conn


def _auth_header(tenant_id="t1", user_id="u1"):
    token, _ = create_access_token(tenant_id=tenant_id, user_id=user_id)
    return {"Authorization": f"Bearer {token}"}


# --- GET /competitors/sources ------------------------------------------

def test_list_sources_requires_auth():
    assert client.get("/competitors/sources").status_code == 401


def test_list_sources_rejects_an_unknown_status_value():
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=_fake_conn()):
        response = client.get("/competitors/sources?status=NOT_A_REAL_STATUS", headers=_auth_header())
    assert response.status_code == 422


def test_list_sources_returns_the_real_sources_and_counts():
    sources = [{
        "source_id": "s1", "source_name": "Real Competitor", "source_url": "https://real-competitor.example/p",
        "collection_method": "WEB_SCRAPE", "policy_status": "RESTRICTED", "collection_justification": None,
        "technical_restrictions": {}, "collector_key": "standards", "created_at": "2026-09-29T00:00:00",
        "approval_reference": None, "approved_at": None, "competitor_name": "Real Competitor",
        "global_competitor_id": "c1", "mapped_product_count": 1,
    }]
    counts = {"ALLOWED": 0, "RESTRICTED": 1, "BLOCKED": 0}
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.competitors.data_access.list_tenant_sources", return_value=sources) as mock_list, \
         patch("src.ai.routers.competitors.data_access.count_tenant_sources_by_status", return_value=counts):
        response = client.get("/competitors/sources?status=RESTRICTED", headers=_auth_header())

    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == sources
    assert body["counts"] == counts
    assert mock_list.call_args.kwargs["policy_status"] == "RESTRICTED"


# --- POST /competitors/sources/{source_id}/review -----------------------

def test_review_source_requires_auth():
    assert client.post("/competitors/sources/s1/review", json={
        "terms_permit": True, "reviewer_reference": "Reviewed, fine.",
    }).status_code == 401


def test_review_source_is_rejected_for_a_non_owner_admin_caller():
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.competitors._require_role", side_effect=HTTPException(
             status_code=403, detail="You do not have permission to perform this action.")):
        response = client.post(
            "/competitors/sources/s1/review", headers=_auth_header(),
            json={"terms_permit": True, "reviewer_reference": "Reviewed, fine."},
        )
    assert response.status_code == 403


def test_review_source_enqueues_real_collection_when_the_result_is_allowed():
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.competitors._require_role", return_value="owner"), \
         patch("src.ai.routers.competitors.source_review.review_source", return_value={
             "source_id": "s1", "status": "ALLOWED", "method": "WEB_SCRAPE", "justification": "ok",
         }), \
         patch("src.ai.routers.competitors.enqueue.enqueue_collection", return_value="123-0") as mock_enqueue:
        response = client.post(
            "/competitors/sources/s1/review", headers=_auth_header(),
            json={"terms_permit": True, "reviewer_reference": "Checked /terms - public catalog."},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ALLOWED"
    assert body["enqueued"] is True
    assert body["enqueue_error"] is None
    mock_enqueue.assert_called_once_with("t1", "s1")


def test_review_source_never_enqueues_when_the_result_is_not_allowed():
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.competitors._require_role", return_value="owner"), \
         patch("src.ai.routers.competitors.source_review.review_source", return_value={
             "source_id": "s1", "status": "BLOCKED", "method": None, "justification": "terms denied",
         }), \
         patch("src.ai.routers.competitors.enqueue.enqueue_collection") as mock_enqueue:
        response = client.post(
            "/competitors/sources/s1/review", headers=_auth_header(),
            json={"terms_permit": False, "reviewer_reference": "Terms explicitly prohibit automated access."},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["enqueued"] is False
    assert body["enqueue_error"] is None
    mock_enqueue.assert_not_called()


def test_review_source_records_a_transient_enqueue_failure_without_failing_the_request():
    """A real, already-committed review decision must never be reported as
    a failure just because Redis is briefly unreachable - the approval
    stands; only the enqueue attempt is reported as failed, and it can
    always be retried."""
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.competitors._require_role", return_value="owner"), \
         patch("src.ai.routers.competitors.source_review.review_source", return_value={
             "source_id": "s1", "status": "ALLOWED", "method": "WEB_SCRAPE", "justification": "ok",
         }), \
         patch("src.ai.routers.competitors.enqueue.enqueue_collection", side_effect=RuntimeError("redis unreachable")):
        response = client.post(
            "/competitors/sources/s1/review", headers=_auth_header(),
            json={"terms_permit": True, "reviewer_reference": "Checked /terms - public catalog."},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ALLOWED"
    assert body["enqueued"] is False
    assert "redis unreachable" in body["enqueue_error"]


def test_review_source_returns_422_for_a_real_value_error():
    conn = _fake_conn()
    with patch("src.ai.routers.competitors.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.competitors._require_role", return_value="owner"), \
         patch("src.ai.routers.competitors.source_review.review_source", side_effect=ValueError("source not found")):
        response = client.post(
            "/competitors/sources/s1/review", headers=_auth_header(),
            json={"terms_permit": True, "reviewer_reference": "Checked /terms - public catalog."},
        )

    assert response.status_code == 422
    assert "source not found" in response.json()["detail"]
    conn.rollback.assert_called_once()
