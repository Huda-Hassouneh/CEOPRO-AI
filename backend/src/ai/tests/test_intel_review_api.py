"""POST /competitors/{id}/intel/review: auth, role, validation and how each
outcome is reported. The database work itself is covered live in
test_intel_review_integration_db.py."""
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from fastapi.testclient import TestClient  # noqa: E402

from src.ai.core.security import create_access_token  # noqa: E402
from src.ai.main import app  # noqa: E402

client = TestClient(app)
COMP = "22222222-2222-2222-2222-222222222222"
INTEL = "33333333-3333-3333-3333-333333333333"
D = "src.ai.routers.discovery"
URL = f"/discovery/competitors/{COMP}/intel/review"


def _auth():
    token, _ = create_access_token(tenant_id="t1", user_id="u1", email_verified=True)
    return {"Authorization": f"Bearer {token}"}


def _post(body, **patches):
    with patch(f"{D}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{D}.intel_review.can_review", return_value=patches.get("can", True)), \
         patch(f"{D}.intel_review.review_fact", **patches.get("review", {"return_value": {"verdict": "CONFIRMED"}})) as review, \
         patch(f"{D}.intel_review.clear_review", return_value=True), \
         patch(f"{D}.competitor_intel.get_intel", return_value={"products": []}), \
         patch("src.market_scraper.market_discovery.pipeline._match_prices", return_value={}) as rematch, \
         patch(f"{D}.tenant_cache.bump"):
        response = client.post(URL, json=body, headers=_auth())
    return response, review, rematch


def test_it_requires_auth_and_valid_input():
    assert client.post(URL, json={"intel_id": INTEL, "verdict": "CONFIRMED"}).status_code == 401
    assert _post({"intel_id": "nope", "verdict": "CONFIRMED"})[0].status_code == 422
    assert _post({"intel_id": INTEL, "verdict": "MAYBE"})[0].status_code == 422
    assert _post({"intel_id": INTEL, "verdict": "CORRECTED", "corrected_price": -1})[0].status_code == 422


def test_only_an_owner_or_admin_may_review():
    response, review, _ = _post({"intel_id": INTEL, "verdict": "CONFIRMED"}, can=False)
    assert response.status_code == 403
    review.assert_not_called()


def test_a_decision_is_recorded_prices_are_rematched_and_the_intel_returned():
    response, review, rematch = _post({"intel_id": INTEL, "verdict": "CORRECTED", "corrected_price": "11.5", "currency": "JOD"})
    assert response.status_code == 200 and response.json()["intel"] == {"products": []}
    args = review.call_args.args
    assert args[3:6] == (INTEL, "CORRECTED", "u1") and str(args[6]) == "11.5" and args[7] == "JOD"
    rematch.assert_called_once()


def test_unknown_fact_is_404_and_bad_combination_is_422():
    assert _post({"intel_id": INTEL, "verdict": "REJECTED"}, review={"side_effect": LookupError("x")})[0].status_code == 404
    from src.ai.market_inputs.intel_review import ReviewError
    response, _r, _m = _post({"intel_id": INTEL, "verdict": "CORRECTED"}, review={"side_effect": ReviewError("needs a price")})
    assert response.status_code == 422 and "needs a price" in response.json()["detail"]


def test_clearing_withdraws_the_decision():
    response, review, _ = _post({"intel_id": INTEL, "verdict": "CLEARED"})
    assert response.status_code == 200 and response.json()["had_decision"] is True
    review.assert_not_called()
