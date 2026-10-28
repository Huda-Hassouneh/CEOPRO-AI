"""
Unit tests for routers/settings.py (profile, company, team management,
security, notification preferences) - offline, same convention as
test_auth_completeness.py: DB calls mocked (db.app_role_connection
replaced with a MagicMock connection, plus the router's own helper
functions where that's the simpler/more faithful mock), real JWT auth
exercised for real via a real access token.
"""
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from src.ai.core.security import create_access_token, hash_password  # noqa: E402
from src.ai.main import app  # noqa: E402

client = TestClient(app)


def _fake_conn():
    conn = MagicMock()
    conn.close = MagicMock()
    return conn


def _cursor(conn):
    return conn.cursor.return_value.__enter__.return_value


def _auth_header(tenant_id="t1", user_id="u1"):
    token, _ = create_access_token(tenant_id=tenant_id, user_id=user_id)
    return {"Authorization": f"Bearer {token}"}


# --- profile ----------------------------------------------------------------

def test_profile_endpoints_require_auth():
    assert client.get("/settings/profile").status_code == 401
    assert client.patch("/settings/profile", json={}).status_code == 401


def test_get_profile_returns_the_callers_own_real_row():
    profile = {
        "user_id": "u1", "email": "jane@example.com", "full_name": "Jane",
        "preferred_language": "en", "email_verified": True,
    }
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.settings._fetch_profile", return_value=profile):
        response = client.get("/settings/profile", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == profile


def test_update_profile_only_sets_the_fields_actually_provided():
    conn = _fake_conn()
    captured = {}

    def _capture_execute(query, params=None):
        if "UPDATE users SET" in query:
            captured["query"] = query
            captured["params"] = params

    _cursor(conn).execute.side_effect = _capture_execute

    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._fetch_profile", return_value={
             "user_id": "u1", "email": "jane@example.com", "full_name": "New Name",
             "preferred_language": "en", "email_verified": False,
         }):
        response = client.patch("/settings/profile", headers=_auth_header(), json={"full_name": "New Name"})

    assert response.status_code == 200
    assert response.json()["full_name"] == "New Name"
    assert "full_name = %s" in captured["query"]
    assert "preferred_language" not in captured["query"]
    assert captured["params"] == ["New Name", "u1"]
    conn.commit.assert_called_once()


# --- company ------------------------------------------------------------

_COMPANY_ROW = (
    "Jane's Shop", "retail", "JO", ["JO"], "JOD", ["JOD"], "Asia/Amman", "en", ["en"],
)
_COMPANY_DICT = dict(zip(
    ("business_name", "business_type", "country_code", "operating_countries", "primary_currency",
     "supported_currencies", "timezone", "preferred_language", "supported_languages"),
    _COMPANY_ROW,
))


def test_get_company_returns_the_tenants_real_row():
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.settings._fetch_company", return_value=_COMPANY_DICT):
        response = client.get("/settings/company", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == _COMPANY_DICT


def test_update_company_is_rejected_for_a_staff_caller():
    conn = _fake_conn()
    _cursor(conn).fetchone.side_effect = [("staff",)]  # _require_role's own SELECT

    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn):
        response = client.patch(
            "/settings/company", headers=_auth_header(), json={"business_name": "New Name"},
        )

    assert response.status_code == 403
    conn.commit.assert_not_called()


def test_update_company_succeeds_for_an_owner_caller():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings._fetch_company", return_value=_COMPANY_DICT):
        response = client.patch(
            "/settings/company", headers=_auth_header(), json={"business_name": "Renamed Shop"},
        )
    assert response.status_code == 200
    conn.commit.assert_called_once()


# --- competitor search scope ---------------------------------------------

_SCOPE_DICT = {
    "country_code": "JO", "operating_countries": ["JO"], "latitude": None, "longitude": None,
    "city": None, "search_scope_level": "PROVINCE", "default_search_radius_km": 150,
}


def test_search_scope_endpoints_require_auth():
    assert client.get("/settings/company/search-scope").status_code == 401
    assert client.patch("/settings/company/search-scope", json={}).status_code == 401


def test_get_search_scope_returns_the_tenants_real_profile():
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.settings.get_tenant_search_scope", return_value=_SCOPE_DICT):
        response = client.get("/settings/company/search-scope", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == _SCOPE_DICT


def test_update_search_scope_is_rejected_for_a_staff_caller():
    conn = _fake_conn()
    _cursor(conn).fetchone.side_effect = [("staff",)]  # _require_role's own SELECT

    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn):
        response = client.patch(
            "/settings/company/search-scope", headers=_auth_header(),
            json={"search_scope_level": "GLOBAL"},
        )
    assert response.status_code == 403
    conn.commit.assert_not_called()


def test_update_search_scope_succeeds_for_an_owner_caller():
    conn = _fake_conn()
    updated = {**_SCOPE_DICT, "search_scope_level": "GLOBAL", "default_search_radius_km": None}
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings.set_tenant_search_scope", return_value=updated) as mock_set:
        response = client.patch(
            "/settings/company/search-scope", headers=_auth_header(),
            json={"search_scope_level": "GLOBAL"},
        )
    assert response.status_code == 200
    assert response.json()["search_scope_level"] == "GLOBAL"
    mock_set.assert_called_once_with(
        conn, "t1", operating_countries=None, latitude=None, longitude=None,
        city=None, search_scope_level="GLOBAL", custom_radius_km=None,
    )


def test_update_search_scope_returns_422_for_an_invalid_scope_level():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings.set_tenant_search_scope", side_effect=ValueError("invalid search_scope_level: 'GALAXY'")):
        response = client.patch(
            "/settings/company/search-scope", headers=_auth_header(),
            json={"search_scope_level": "GALAXY"},
        )
    assert response.status_code == 422
    assert "GALAXY" in response.json()["detail"]
    conn.rollback.assert_called_once()


# --- target markets --------------------------------------------------------

def test_target_markets_endpoints_require_auth():
    assert client.get("/settings/company/target-markets").status_code == 401
    assert client.put("/settings/company/target-markets", json={}).status_code == 401


def test_get_target_markets_returns_the_tenants_real_declared_list():
    stored = [
        {"market_type": "COUNTRY", "country_code": "AE", "region_name": None},
        {"market_type": "COUNTRY", "country_code": "JO", "region_name": None},
    ]
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.settings.get_tenant_target_markets", return_value=stored):
        response = client.get("/settings/company/target-markets", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == {"target_markets": stored}


def test_get_target_markets_is_an_empty_list_when_nothing_declared():
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=_fake_conn()), \
         patch("src.ai.routers.settings.get_tenant_target_markets", return_value=[]):
        response = client.get("/settings/company/target-markets", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == {"target_markets": []}


def test_update_target_markets_is_rejected_for_a_staff_caller():
    conn = _fake_conn()
    _cursor(conn).fetchone.side_effect = [("staff",)]  # _require_role's own SELECT

    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn):
        response = client.put(
            "/settings/company/target-markets", headers=_auth_header(),
            json={"target_markets": [{"market_type": "COUNTRY", "country_code": "JO"}]},
        )
    assert response.status_code == 403
    conn.commit.assert_not_called()


def test_update_target_markets_succeeds_for_an_owner_caller():
    conn = _fake_conn()
    normalized = [
        {"market_type": "COUNTRY", "country_code": "AE", "region_name": None},
        {"market_type": "COUNTRY", "country_code": "JO", "region_name": None},
    ]
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings.set_tenant_target_markets", return_value=normalized) as mock_set:
        response = client.put(
            "/settings/company/target-markets", headers=_auth_header(),
            json={"target_markets": [
                {"market_type": "COUNTRY", "country_code": "jo"},
                {"market_type": "COUNTRY", "country_code": "ae"},
            ]},
        )
    assert response.status_code == 200
    assert response.json() == {"target_markets": normalized}
    mock_set.assert_called_once_with(conn, "t1", [
        {"market_type": "COUNTRY", "country_code": "jo", "region_name": None},
        {"market_type": "COUNTRY", "country_code": "ae", "region_name": None},
    ])


def test_update_target_markets_supports_a_region_entry():
    conn = _fake_conn()
    normalized = [{"market_type": "REGION", "country_code": None, "region_name": "Europe"}]
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings.set_tenant_target_markets", return_value=normalized) as mock_set:
        response = client.put(
            "/settings/company/target-markets", headers=_auth_header(),
            json={"target_markets": [{"market_type": "REGION", "region_name": "Europe"}]},
        )
    assert response.status_code == 200
    assert response.json() == {"target_markets": normalized}
    mock_set.assert_called_once_with(conn, "t1", [
        {"market_type": "REGION", "country_code": None, "region_name": "Europe"},
    ])


def test_update_target_markets_supports_a_global_entry():
    conn = _fake_conn()
    normalized = [{"market_type": "GLOBAL", "country_code": None, "region_name": None}]
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings.set_tenant_target_markets", return_value=normalized) as mock_set:
        response = client.put(
            "/settings/company/target-markets", headers=_auth_header(),
            json={"target_markets": [{"market_type": "GLOBAL"}]},
        )
    assert response.status_code == 200
    assert response.json() == {"target_markets": normalized}
    mock_set.assert_called_once_with(conn, "t1", [
        {"market_type": "GLOBAL", "country_code": None, "region_name": None},
    ])


def test_update_target_markets_returns_422_for_an_invalid_country_code():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings.set_tenant_target_markets", side_effect=ValueError("invalid country code: 'Jordan' (expected a 2-letter ISO code)")):
        response = client.put(
            "/settings/company/target-markets", headers=_auth_header(),
            json={"target_markets": [{"market_type": "COUNTRY", "country_code": "Jordan"}]},
        )
    assert response.status_code == 422
    assert "Jordan" in response.json()["detail"]
    conn.rollback.assert_called_once()


def test_update_target_markets_returns_422_for_global_combined_with_a_country():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings.set_tenant_target_markets", side_effect=ValueError("GLOBAL cannot be combined with specific country/region target markets")):
        response = client.put(
            "/settings/company/target-markets", headers=_auth_header(),
            json={"target_markets": [{"market_type": "GLOBAL"}, {"market_type": "COUNTRY", "country_code": "AE"}]},
        )
    assert response.status_code == 422
    assert "GLOBAL cannot be combined" in response.json()["detail"]
    conn.rollback.assert_called_once()


def test_update_target_markets_with_an_empty_list_clears_the_declared_list():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings.set_tenant_target_markets", return_value=[]) as mock_set:
        response = client.put(
            "/settings/company/target-markets", headers=_auth_header(), json={"target_markets": []},
        )
    assert response.status_code == 200
    assert response.json() == {"target_markets": []}
    mock_set.assert_called_once_with(conn, "t1", [])


# --- team ---------------------------------------------------------------

def test_list_team_members_returns_only_active_real_members():
    conn = _fake_conn()
    joined = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _cursor(conn).fetchall.return_value = [
        ("tu1", "u1", "jane@example.com", "Jane", "owner", joined),
        ("tu2", "u2", "bob@example.com", "Bob", "staff", joined),
    ]
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn):
        response = client.get("/settings/team/members", headers=_auth_header())
    assert response.status_code == 200
    members = response.json()["members"]
    assert len(members) == 2
    assert members[0]["role_key"] == "owner"
    assert members[1]["email"] == "bob@example.com"


def test_invite_team_member_rejects_an_unknown_role_key():
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=_fake_conn()):
        response = client.post(
            "/settings/team/invitations", headers=_auth_header(),
            json={"email": "new@example.com", "role_key": "superadmin"},
        )
    assert response.status_code == 400


def test_invite_team_member_is_rejected_for_a_non_admin_caller():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", side_effect=HTTPException(
             status_code=403, detail="You do not have permission to perform this action.")):
        response = client.post(
            "/settings/team/invitations", headers=_auth_header(),
            json={"email": "new@example.com", "role_key": "staff"},
        )
    assert response.status_code == 403


def test_invite_team_member_creates_a_token_and_sends_the_real_email():
    conn = _fake_conn()
    _cursor(conn).fetchone.return_value = ("Jane's Shop",)  # SELECT business_name

    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings._ensure_seat_for_invitation"), \
         patch("src.ai.routers.settings.notifications.send_team_invitation_email", return_value=True) as mock_send:
        response = client.post(
            "/settings/team/invitations", headers=_auth_header(),
            json={"email": "new@example.com", "role_key": "staff"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "email_sent": True}
    # the raw token is never present in the response
    assert "token" not in response.text
    mock_send.assert_called_once()
    call_args = mock_send.call_args[0]
    assert call_args[0] == "new@example.com"
    assert call_args[1] == "Jane's Shop"
    conn.commit.assert_called_once()


def test_update_team_member_role_succeeds_for_a_non_owner_target():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings._fetch_active_member", return_value=("tu2", "u2", "staff")):
        response = client.patch(
            "/settings/team/members/tu2", headers=_auth_header(), json={"role_key": "manager"},
        )
    assert response.status_code == 200
    assert response.json()["role_key"] == "manager"
    conn.commit.assert_called_once()


def test_update_team_member_role_blocks_demoting_the_last_owner():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings._fetch_active_member", return_value=("tu1", "u1", "owner")), \
         patch("src.ai.routers.settings._count_active_owners", return_value=1):
        response = client.patch(
            "/settings/team/members/tu1", headers=_auth_header(), json={"role_key": "staff"},
        )
    assert response.status_code == 400
    conn.commit.assert_not_called()


def test_update_team_member_role_allows_demoting_an_owner_when_another_owner_remains():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings._fetch_active_member", return_value=("tu1", "u1", "owner")), \
         patch("src.ai.routers.settings._count_active_owners", return_value=2):
        response = client.patch(
            "/settings/team/members/tu1", headers=_auth_header(), json={"role_key": "admin"},
        )
    assert response.status_code == 200
    conn.commit.assert_called_once()


def test_remove_team_member_blocks_removing_the_last_owner():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings._fetch_active_member", return_value=("tu1", "u1", "owner")), \
         patch("src.ai.routers.settings._count_active_owners", return_value=1):
        response = client.delete("/settings/team/members/tu1", headers=_auth_header())
    assert response.status_code == 400
    conn.commit.assert_not_called()


def test_remove_team_member_soft_deletes_a_real_non_owner_member():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings._fetch_active_member", return_value=("tu2", "u2", "staff")):
        response = client.delete("/settings/team/members/tu2", headers=_auth_header())
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    executed = _cursor(conn).execute.call_args[0][0]
    assert "removed_at = NOW()" in executed
    conn.commit.assert_called_once()


def test_remove_team_member_returns_404_for_a_member_outside_this_tenant():
    conn = _fake_conn()
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings._fetch_active_member", return_value=None):
        response = client.delete("/settings/team/members/does-not-exist", headers=_auth_header())
    assert response.status_code == 404


# --- security -------------------------------------------------------------

_REAL_HASH = hash_password("correct horse battery staple")


def test_change_password_rejects_the_wrong_current_password():
    conn = _fake_conn()
    _cursor(conn).fetchone.return_value = (_REAL_HASH,)
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn):
        response = client.post(
            "/settings/security/change-password", headers=_auth_header(),
            json={"current_password": "wrong password", "new_password": "Str0ng!Passw0rd"},
        )
    assert response.status_code == 400
    conn.commit.assert_not_called()


def test_change_password_accepts_the_right_current_password_and_commits():
    conn = _fake_conn()
    _cursor(conn).fetchone.return_value = (_REAL_HASH,)
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn):
        response = client.post(
            "/settings/security/change-password", headers=_auth_header(),
            json={"current_password": "correct horse battery staple", "new_password": "Str0ng!Passw0rd"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["access_token"]  # the current session continues on a fresh token; every other one is signed out
    conn.commit.assert_called_once()


def test_security_sessions_gives_an_honest_answer_not_a_fabricated_list():
    response = client.get("/settings/security/sessions", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    assert body["sessions"] == []
    assert "does not track sessions" in body["note"]


# --- notification preferences ----------------------------------------------

def test_get_notification_preferences_fills_defaults_and_reports_email_status():
    conn = _fake_conn()
    _cursor(conn).fetchone.return_value = ({"in_app": {"market": False}, "low_stock_alerts": True}, True)
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn):
        response = client.get("/settings/notifications", headers=_auth_header())
    assert response.status_code == 200
    body = response.json()
    prefs = body["notification_preferences"]
    assert prefs["in_app"]["market"] is False and prefs["in_app"]["stock"] is True
    assert prefs["email_frequency"] == "off" and set(prefs) == {"in_app", "email", "email_frequency"}
    assert body["email_verified"] is True and "email_delivery_available" in body


def test_patch_notification_preferences_changes_only_what_was_sent():
    conn = _fake_conn()
    _cursor(conn).fetchone.return_value = ({"in_app": {"market": False}}, False)
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn):
        response = client.patch(
            "/settings/notifications", headers=_auth_header(), json={"email_frequency": "daily", "email": {"billing": False}},
        )
    assert response.status_code == 200
    prefs = response.json()["notification_preferences"]
    assert prefs["email_frequency"] == "daily" and prefs["email"]["billing"] is False
    assert prefs["in_app"]["market"] is False and prefs["email"]["stock"] is True
    conn.commit.assert_called_once()


def test_patch_notification_preferences_refuses_unknown_settings():
    conn = _fake_conn()
    _cursor(conn).fetchone.return_value = ({}, True)
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn):
        for bad in ({"email_frequency": "hourly"}, {"in_app": {"weather": True}}, {"in_app": {"stock": "yes"}}, {"sms": True}):
            assert client.patch("/settings/notifications", headers=_auth_header(), json=bad).status_code == 422
    conn.commit.assert_not_called()


def test_an_invitation_saved_without_an_email_says_so():
    """No email service (or a failed send): the invitation is kept, but the
    screen must not report it as sent."""
    conn = _fake_conn()
    _cursor(conn).fetchone.return_value = ("Jane's Shop",)
    with patch("src.ai.routers.settings.db.app_role_connection", return_value=conn), \
         patch("src.ai.routers.settings._require_role", return_value="owner"), \
         patch("src.ai.routers.settings._ensure_seat_for_invitation"), \
         patch("src.ai.routers.settings.notifications.send_team_invitation_email", return_value=False):
        response = client.post(
            "/settings/team/invitations", headers=_auth_header(),
            json={"email": "new@example.com", "role_key": "staff"},
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "email_sent": False}
    conn.commit.assert_called_once()
