"""Match endpoints: auth, owner/admin gate, validation and how each outcome is reported. The database work is covered
live in test_price_changes_and_matches_integration_db.py."""
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from fastapi.testclient import TestClient  # noqa: E402

from src.ai.core.security import create_access_token  # noqa: E402
from src.ai.main import app  # noqa: E402
from src.ai.market_inputs.product_matches import MatchError  # noqa: E402

client = TestClient(app)
COMP = "22222222-2222-2222-2222-222222222222"
PROD = "44444444-4444-4444-4444-444444444444"
INTEL = "33333333-3333-3333-3333-333333333333"
D = "src.ai.routers.discovery"


def _auth():
    token, _ = create_access_token(tenant_id="t1", user_id="u1")
    return {"Authorization": f"Bearer {token}"}


def _call(method, path, body=None, can=True, **action):
    with patch(f"{D}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{D}.product_matches.can_manage", return_value=can), \
         patch(f"{D}.competitor_intel.competitor_website", return_value="https://x.jo"), \
         patch(f"{D}.product_matches.list_matches", return_value={"matches": [], "items": [], "rejected": []}), \
         patch(f"{D}.tenant_cache.bump"), \
         patch(f"{D}.product_matches.reject_match", **action.get("reject", {"return_value": {"new_match": None}})) as reject, \
         patch(f"{D}.product_matches.choose_match", **action.get("choose", {"return_value": {"new_match": None}})) as choose, \
         patch(f"{D}.product_matches.clear_match", **action.get("clear", {"return_value": {"cleared": 1, "new_match": None}})) as clear:
        response = client.request(method, path, json=body, headers=_auth())
    return response, {"reject": reject, "choose": choose, "clear": clear}


def test_the_match_endpoints_need_login_and_valid_ids():
    for method, path in (("GET", f"/discovery/competitors/{COMP}/matches"), ("POST", f"/discovery/competitors/{COMP}/matches/reject"),
                         ("POST", f"/discovery/competitors/{COMP}/matches"), ("DELETE", f"/discovery/competitors/{COMP}/matches/{PROD}"),
                         ("GET", f"/discovery/competitors/{COMP}/price-changes"), ("GET", "/discovery/price-changes")):
        assert client.request(method, path).status_code == 401, (method, path)
    assert _call("POST", f"/discovery/competitors/{COMP}/matches/reject", {"product_id": "nope"})[0].status_code == 422
    assert _call("POST", f"/discovery/competitors/{COMP}/matches", {"product_id": PROD})[0].status_code == 422  # intel_id missing


def test_only_an_owner_or_admin_may_change_a_match():
    for method, path, body in (("POST", f"/discovery/competitors/{COMP}/matches/reject", {"product_id": PROD}),
                               ("POST", f"/discovery/competitors/{COMP}/matches", {"product_id": PROD, "intel_id": INTEL}),
                               ("DELETE", f"/discovery/competitors/{COMP}/matches/{PROD}", None)):
        response, calls = _call(method, path, body, can=False)
        assert response.status_code == 403
        assert not any(c.called for c in calls.values())


def test_each_decision_reaches_the_right_function_and_returns_the_fresh_matches():
    response, calls = _call("POST", f"/discovery/competitors/{COMP}/matches/reject", {"product_id": PROD})
    assert response.status_code == 200 and response.json()["matches"] == [] and calls["reject"].call_args.args[3] == PROD
    response, calls = _call("POST", f"/discovery/competitors/{COMP}/matches", {"product_id": PROD, "intel_id": INTEL})
    assert response.status_code == 200 and calls["choose"].call_args.args[3:5] == (PROD, INTEL)
    response, calls = _call("DELETE", f"/discovery/competitors/{COMP}/matches/{PROD}")
    assert response.status_code == 200 and response.json()["cleared"] == 1


def test_unknown_things_are_404_and_a_refused_choice_is_422_with_its_reason():
    response, _ = _call("POST", f"/discovery/competitors/{COMP}/matches/reject", {"product_id": PROD}, reject={"side_effect": LookupError("x")})
    assert response.status_code == 404
    response, _ = _call("POST", f"/discovery/competitors/{COMP}/matches", {"product_id": PROD, "intel_id": INTEL},
                        choose={"side_effect": MatchError("confirm this price first")})
    assert response.status_code == 422 and "confirm this price first" in response.json()["detail"]


def test_price_change_lists_validate_their_window_and_pass_the_flags():
    with patch(f"{D}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{D}.competitor_intel.competitor_website", return_value="x"), \
         patch(f"{D}.price_history.list_changes", return_value=[{"item": "Mansaf"}]) as listing:
        ok = client.get(f"/discovery/competitors/{COMP}/price-changes?days=30&include_unreliable=true&limit=5", headers=_auth())
        assert ok.status_code == 200 and ok.json()["changes"] == [{"item": "Mansaf"}]
        assert listing.call_args.args[3:6] == (30, True, 5)
        assert client.get(f"/discovery/competitors/{COMP}/price-changes?days=0", headers=_auth()).status_code == 422
        assert client.get("/discovery/price-changes?limit=999", headers=_auth()).status_code == 422
        assert client.get("/discovery/price-changes", headers=_auth()).json()["days"] == 30
