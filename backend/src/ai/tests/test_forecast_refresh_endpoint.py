"""The Demand page's "Refresh forecasts" really recomputes.

Found on keelai.net (VELORA): after back-to-back imports the stored forecasts
were about a tenth of real demand, and pressing Refresh forecasts ran
("5 of 28 products done") but left every number unchanged, because the
refresh reused the stale forecasts as "fresh".
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.ai.routers import forecasting


def _call(all_products):
    ctx = SimpleNamespace(tenant_id="t1", user_id="u1")
    with patch.object(forecasting.db, "app_role_connection", return_value=MagicMock()), \
         patch.object(forecasting.forecast_refresh, "products_needing_forecast", return_value=["p1", "p2"]) as needing, \
         patch.object(forecasting.forecast_refresh, "start_refresh", return_value=True) as start, \
         patch.object(forecasting, "_refresh_payload", side_effect=lambda tenant, n, started: {"n": n, "started": started}):
        result = forecasting.refresh_forecasts(all_products=all_products, ctx=ctx)
    return result, needing, start


def test_refresh_forecasts_button_forces_regeneration_of_every_product():
    result, needing, start = _call(all_products=True)
    assert result == {"n": 2, "started": True}
    assert needing.call_args.kwargs["stale_after_hours"] == 0
    start.assert_called_once_with("t1", "u1", ["p1", "p2"], force=True)


def test_a_plain_stale_only_refresh_keeps_reuse():
    _result, _needing, start = _call(all_products=False)
    start.assert_called_once_with("t1", "u1", ["p1", "p2"], force=False)
