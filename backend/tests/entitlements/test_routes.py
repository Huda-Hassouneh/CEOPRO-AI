"""Static security regressions; these do not boot models or prove deployed ACLs."""

from scripts.entitlement_verification import route_inventory


def test_router_inventory_has_unique_methods_and_paths():
    routes = route_inventory()
    pairs = [(r["method"], r["path"]) for r in routes]
    assert len(routes) > 100
    assert len(pairs) == len(set(pairs))


def test_forecasting_router_keeps_module_gate():
    routes = [r for r in route_inventory() if r["path"].startswith("/forecasting/")]
    assert len(routes) == 3
    assert all(
        "DEMAND_PREDICTION" in " ".join(r["router_dependencies"]) for r in routes
    )


def test_dashboard_forecast_alias_has_same_gate_as_forecasting_router():
    route = next(
        r
        for r in route_inventory()
        if r["path"] == "/dashboard/products/{product_id}/forecast"
        and r["method"] == "POST"
    )
    # Desired security contract; intentionally fails while protected main.py /
    # dashboard handler and underlying forecast pipeline contain no such gate.
    evidence = " ".join(
        route["router_dependencies"]
        + route["route_dependencies"]
        + route["direct_security_calls"]
    )
    assert "DEMAND_PREDICTION" in evidence or "usage.require_entitlement" in evidence, (
        "Dashboard forecast alias bypasses the forecasting module dependency"
    )
