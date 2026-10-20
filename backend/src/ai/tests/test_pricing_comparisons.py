"""
pricing/comparisons.py (ladder shaping) and the /pricing/comparisons routes. Offline: the database is mocked.
"""
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests")

from fastapi.testclient import TestClient  # noqa: E402

from src.ai.core.security import create_access_token  # noqa: E402
from src.ai.main import app  # noqa: E402
from src.ai.pricing import comparisons  # noqa: E402

client = TestClient(app)
PID = "11111111-1111-1111-1111-111111111111"
R = "src.ai.routers.pricing"
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
PRODUCT = {"product_id": PID, "current_price": 6.0, "currency": "JOD"}


def _auth():
    token, _ = create_access_token(tenant_id="t1", user_id="u1")
    return {"Authorization": f"Bearer {token}"}


def _row(tier, competitor, comparable, score=0.8, premium=None, delta=None):
    return {"tier": tier, "competitor_id": competitor, "competitor_name": competitor.upper(), "item_name": "item",
            "competitor_price": comparable, "scale_factor": 1.0, "comparable_price": comparable, "currency": "JOD",
            "price_delta_pct": delta, "direction": "same", "match_score": score, "reasons": [], "premium": premium,
            "source_url": None, "observed_at": NOW}


def test_ladder_groups_by_tier_and_the_headline_is_the_best_like_for_like_tier():
    ladder = comparisons.build_ladder(PRODUCT, [
        _row("SIMILAR", "a", 5.0), _row("SIMILAR", "b", 7.0), _row("EQUIVALENT", "c", 5.0),
        _row("ADDED_VALUE", "d", 4.0, premium={"premium_pct": 50.0, "status": "within_range", "band_pct": 60}),
    ], [])
    assert {t: ladder["tiers"][t]["count"] for t in comparisons.TIERS} == {"EXACT": 0, "EQUIVALENT": 1, "SIMILAR": 2, "ADDED_VALUE": 1}
    assert ladder["headline"] == {"tier": "EQUIVALENT", "count": 1, "median_comparable": 5.0, "position_pct": 20.0, "direction": "same"}
    assert ladder["tiers"]["SIMILAR"]["median"] == 6.0 and ladder["tiers"]["SIMILAR"]["your_position_pct"] == 0.0
    assert ladder["covered"] is True


def test_added_value_alone_is_covered_but_never_hides_a_like_for_like_tier():
    only = comparisons.build_ladder(PRODUCT, [_row("ADDED_VALUE", "d", 4.0)], [])
    assert only["headline"]["tier"] == "ADDED_VALUE"
    mixed = comparisons.build_ladder(PRODUCT, [_row("ADDED_VALUE", "d", 4.0), _row("SIMILAR", "a", 5.0)], [])
    assert mixed["headline"]["tier"] == "SIMILAR"


def test_similar_items_that_are_not_like_for_like_do_not_set_the_headline_of_a_richer_product():
    leaner = {**_row("SIMILAR", "a", 2.8), "direction": "own_richer"}
    added = _row("ADDED_VALUE", "b", 3.0, premium={"premium_pct": 100.0, "status": "above_range", "band_pct": 60})
    ladder = comparisons.build_ladder(PRODUCT, [leaner, added], [])
    assert ladder["headline"]["tier"] == "ADDED_VALUE"
    assert ladder["tiers"]["SIMILAR"]["direction"] == "own_richer"
    # With nothing better the directional tier still speaks, and says which way it leans.
    only = comparisons.build_ladder(PRODUCT, [leaner], [])
    assert only["headline"]["tier"] == "SIMILAR" and only["headline"]["direction"] == "own_richer"


def test_a_tier_whose_items_disagree_on_direction_is_mixed():
    rows = [{**_row("SIMILAR", "a", 5.0), "direction": "own_richer"}, {**_row("SIMILAR", "b", 6.0), "direction": "own_leaner"}]
    assert comparisons.build_ladder(PRODUCT, rows, [])["tiers"]["SIMILAR"]["direction"] == "mixed"


def test_recorded_exact_prices_join_the_exact_tier_without_duplicating_a_competitor():
    exact = [{"competitor_id": "a", "competitor_name": "A", "price": 5.0, "currency": "JOD", "observed_at": NOW, "source_url": None},
             {"competitor_id": "b", "competitor_name": "B", "price": 4.0, "currency": "JOD", "observed_at": NOW, "source_url": None}]
    ladder = comparisons.build_ladder(PRODUCT, [_row("EXACT", "a", 5.0)], exact)
    assert ladder["tiers"]["EXACT"]["count"] == 2
    assert ladder["headline"]["tier"] == "EXACT" and ladder["headline"]["median_comparable"] == 4.5


def test_no_evidence_is_not_covered():
    ladder = comparisons.build_ladder(PRODUCT, [], [])
    assert ladder["covered"] is False and ladder["headline"] is None
    assert all(ladder["tiers"][t]["items"] == [] for t in comparisons.TIERS)


def test_routes_require_auth():
    assert client.get(f"/pricing/comparisons/{PID}").status_code == 401
    assert client.get(f"/pricing/comparisons?product_ids={PID}").status_code == 401
    assert client.post("/pricing/comparisons/refresh").status_code == 401


def test_summary_rejects_bad_and_oversized_id_lists():
    assert client.get("/pricing/comparisons?product_ids=nope", headers=_auth()).status_code == 422
    too_many = ",".join([PID] * 101)
    assert client.get(f"/pricing/comparisons?product_ids={too_many}", headers=_auth()).status_code == 422


def test_ladder_route_returns_the_ladder_and_404s_for_an_unknown_product():
    ladder = comparisons.build_ladder(PRODUCT, [_row("EXACT", "a", 5.0)], [])
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.price_comparisons.get_ladders", return_value={PID: ladder}):
        body = client.get(f"/pricing/comparisons/{PID}", headers=_auth()).json()
    assert body["headline"]["tier"] == "EXACT" and body["tiers"]["EXACT"]["items"][0]["competitor_name"] == "A"
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), patch(f"{R}.price_comparisons.get_ladders", return_value={}):
        assert client.get(f"/pricing/comparisons/{PID}", headers=_auth()).status_code == 404


def test_summary_route_returns_counts_only():
    ladder = comparisons.build_ladder(PRODUCT, [_row("SIMILAR", "a", 5.0)], [])
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), \
         patch(f"{R}.price_comparisons.get_ladders", return_value={PID: ladder}):
        body = client.get(f"/pricing/comparisons?product_ids={PID}", headers=_auth()).json()
    assert body["products"][PID]["counts"] == {"EXACT": 0, "EQUIVALENT": 0, "SIMILAR": 1, "ADDED_VALUE": 0}
    assert "tiers" not in body["products"][PID]


def test_refresh_route_commits_the_engine_result():
    conn = MagicMock()
    result = {"competitors": 2, "rows": 5, "unsettled": 0, "by_tier": {"EXACT": 1, "EQUIVALENT": 1, "SIMILAR": 2, "ADDED_VALUE": 1}}
    with patch(f"{R}.db.app_role_connection", return_value=conn), patch(f"{R}.comparison_engine.refresh_for_tenant", return_value=result) as refresh, \
         patch(f"{R}._ai_comparison_pass") as background:
        response = client.post("/pricing/comparisons/refresh", headers=_auth())
    assert response.status_code == 200 and response.json() == {**result, "ai_pending": 0}
    conn.commit.assert_called_once()
    assert refresh.call_args.kwargs.get("judge") is None  # the request never waits on the model
    background.assert_not_called()


def test_refresh_answers_at_once_and_leaves_unclear_pairs_to_a_background_ai_pass():
    result = {"competitors": 1, "rows": 3, "unsettled": 2, "by_tier": {"EXACT": 0, "EQUIVALENT": 0, "SIMILAR": 3, "ADDED_VALUE": 0}}
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), patch(f"{R}.comparison_engine.refresh_for_tenant", return_value=result), \
         patch(f"{R}._ai_comparison_pass") as background, patch.dict("os.environ", {"DISCOVERY_AI_HINTS": "true"}):
        body = client.post("/pricing/comparisons/refresh", headers=_auth()).json()
    assert body["ai_pending"] == 2
    background.assert_called_once_with("t1", "u1")
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), patch(f"{R}.comparison_engine.refresh_for_tenant", return_value=result), \
         patch(f"{R}._ai_comparison_pass") as background, patch.dict("os.environ", {"DISCOVERY_AI_HINTS": "false"}):
        assert client.post("/pricing/comparisons/refresh", headers=_auth()).json()["ai_pending"] == 0
    background.assert_not_called()


def test_the_background_pass_uses_its_own_connection_asks_the_model_and_never_raises():
    conn = MagicMock()
    with patch(f"{R}.db.dedicated_tenant_connection", return_value=conn), patch.dict("os.environ", {"DISCOVERY_AI_HINTS": "true"}), \
         patch(f"{R}.comparison_engine.refresh_for_tenant", return_value={"rows": 1, "unsettled": 0}) as refresh:
        from src.ai.routers import pricing
        pricing._ai_comparison_pass("t1", "u1")
    assert refresh.call_args.kwargs["judge"] is not None
    conn.commit.assert_called_once(); conn.close.assert_called_once()
    conn = MagicMock()
    with patch(f"{R}.db.dedicated_tenant_connection", return_value=conn), patch.dict("os.environ", {"DISCOVERY_AI_HINTS": "true"}), \
         patch(f"{R}.comparison_engine.refresh_for_tenant", side_effect=RuntimeError("boom")):
        pricing._ai_comparison_pass("t1", "u1")
    conn.rollback.assert_called_once(); conn.close.assert_called_once()


def _override_conn(role):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [(role,), (1,), (1,)]
    return conn, cursor


BODY = {"competitor_id": "22222222-2222-2222-2222-222222222222", "item_name": "30 min class", "verdict": "ADDITION"}


def test_override_requires_auth_and_owner_or_admin():
    assert client.put(f"/pricing/comparisons/{PID}/override", json=BODY).status_code == 401
    conn, _ = _override_conn("staff")
    with patch(f"{R}.db.app_role_connection", return_value=conn):
        assert client.put(f"/pricing/comparisons/{PID}/override", json=BODY, headers=_auth()).status_code == 403


def test_override_rejects_an_unknown_verdict():
    assert client.put(f"/pricing/comparisons/{PID}/override", json={**BODY, "verdict": "MAYBE"}, headers=_auth()).status_code == 422


def test_override_saves_recomputes_and_returns_the_ladder():
    conn, cursor = _override_conn("owner")
    ladder = comparisons.build_ladder(PRODUCT, [_row("ADDED_VALUE", "d", 4.0)], [])
    with patch(f"{R}.db.app_role_connection", return_value=conn), \
         patch(f"{R}.comparison_offerings.company_products", return_value=[]), \
         patch(f"{R}.comparison_engine.refresh_for_competitor") as refresh, \
         patch(f"{R}.price_comparisons.get_ladders", return_value={PID: ladder}):
        response = client.put(f"/pricing/comparisons/{PID}/override", json=BODY, headers=_auth())
    assert response.status_code == 200 and response.json()["headline"]["tier"] == "ADDED_VALUE"
    sql = " ".join(call.args[0] for call in cursor.execute.call_args_list)
    assert "INSERT INTO product_price_comparison_overrides" in sql
    refresh.assert_called_once()
    conn.commit.assert_called_once()


def test_override_null_clears_the_decision_and_unknown_targets_are_404():
    conn, cursor = _override_conn("admin")
    with patch(f"{R}.db.app_role_connection", return_value=conn), patch(f"{R}.comparison_offerings.company_products", return_value=[]), \
         patch(f"{R}.comparison_engine.refresh_for_competitor"), patch(f"{R}.price_comparisons.get_ladders", return_value={PID: {}}):
        assert client.put(f"/pricing/comparisons/{PID}/override", json={**BODY, "verdict": None}, headers=_auth()).status_code == 200
    assert "DELETE FROM product_price_comparison_overrides" in " ".join(c.args[0] for c in cursor.execute.call_args_list)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.side_effect = [("owner",), None, (1,)]
    with patch(f"{R}.db.app_role_connection", return_value=conn):
        assert client.put(f"/pricing/comparisons/{PID}/override", json=BODY, headers=_auth()).status_code == 404


def test_price_comparison_report_needs_auth_and_returns_the_overview():
    assert client.get("/reports/price-comparison").status_code == 401
    entry = {"name": "Burger", **comparisons.build_ladder(PRODUCT, [_row("EXACT", "a", 5.0)], [])}
    with patch("src.ai.routers.reports.db.app_role_connection", return_value=MagicMock()), \
         patch("src.ai.routers.reports.price_comparisons.ladder_overview", return_value=[entry]) as overview:
        body = client.get("/reports/price-comparison?limit=5", headers=_auth()).json()
    assert body["count"] == 1 and body["products"][0]["name"] == "Burger"
    assert overview.call_args.args[2] == 5


PAYLOAD = {"default_band_pct": 60.0, "categories": []}


def test_premium_bands_need_auth_and_the_set_endpoint_is_owner_or_admin_only():
    assert client.get("/pricing/premium-bands").status_code == 401
    assert client.put("/pricing/premium-bands", json={"category": "burgers", "band_pct": 40}).status_code == 401
    assert client.put("/pricing/premium-bands", json={"category": "burgers", "band_pct": 2}, headers=_auth()).status_code == 422
    assert client.put("/pricing/premium-bands", json={"category": "burgers", "band_pct": 900}, headers=_auth()).status_code == 422
    conn, _ = _override_conn("staff")
    with patch(f"{R}.db.app_role_connection", return_value=conn):
        assert client.put("/pricing/premium-bands", json={"category": "burgers", "band_pct": 40}, headers=_auth()).status_code == 403


def test_setting_and_clearing_a_premium_band():
    conn, cursor = _override_conn("owner")
    cursor.fetchone.side_effect = [("owner",), (0, False)]
    with patch(f"{R}.db.app_role_connection", return_value=conn), patch(f"{R}._bands_payload", return_value=PAYLOAD):
        response = client.put("/pricing/premium-bands", json={"category": " Burgers ", "band_pct": 40}, headers=_auth())
    assert response.status_code == 200 and response.json() == PAYLOAD
    insert = next(c for c in cursor.execute.call_args_list if "INSERT INTO price_premium_band_overrides" in c.args[0])
    assert insert.args[1][1] == "burgers" and insert.args[1][2] == 40
    conn, cursor = _override_conn("admin")
    with patch(f"{R}.db.app_role_connection", return_value=conn), patch(f"{R}._bands_payload", return_value=PAYLOAD):
        assert client.put("/pricing/premium-bands", json={"category": None, "band_pct": None}, headers=_auth()).status_code == 200
    delete = next(c for c in cursor.execute.call_args_list if "DELETE FROM price_premium_band_overrides" in c.args[0])
    assert delete.args[1][1] == "__none__"


def test_the_number_of_owner_set_bands_is_capped():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [("owner",), (200, False)]
    with patch(f"{R}.db.app_role_connection", return_value=conn):
        response = client.put("/pricing/premium-bands", json={"category": "one more", "band_pct": 40}, headers=_auth())
    assert response.status_code == 409
    cursor.fetchone.side_effect = [("owner",), (200, True)]  # changing one that already exists is fine
    with patch(f"{R}.db.app_role_connection", return_value=conn), patch(f"{R}._bands_payload", return_value=PAYLOAD):
        assert client.put("/pricing/premium-bands", json={"category": "burgers", "band_pct": 40}, headers=_auth()).status_code == 200


def test_read_premium_bands():
    with patch(f"{R}.db.app_role_connection", return_value=MagicMock()), patch(f"{R}._bands_payload", return_value=PAYLOAD):
        assert client.get("/pricing/premium-bands", headers=_auth()).json() == PAYLOAD
