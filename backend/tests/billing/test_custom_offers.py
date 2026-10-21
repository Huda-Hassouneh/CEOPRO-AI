import pytest

from src.ai.billing import admin, custom_offers


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params):
        self.query, self.params = query, params

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, rows):
        self._cursor = Cursor(rows)
        self.writes = 0

    def cursor(self):
        return self._cursor

    def close(self):
        return None


@pytest.fixture
def connection(monkeypatch):
    allowed = tuple(sorted(admin._NUMERIC_CONTRACT_FEATURES))
    rows = [(allowed[0], "records", "max", "billing_period"), (allowed[1], "MB", "sum", "billing_period")]
    monkeypatch.setattr(admin, "_NUMERIC_CONTRACT_FEATURES", allowed)
    return Connection(rows), allowed


def test_configurator_lists_only_existing_python_contract_features_and_units(connection):
    conn, allowed = connection
    result = custom_offers.feature_catalog(conn)

    assert [item["featureCode"] for item in result] == list(allowed[:2])
    assert [item["unit"] for item in result] == ["records", "MB"]
    assert all(item["unlimitedOverrideSupported"] is False for item in result)
    assert "SELECT feature_code" in conn._cursor.query
    assert "INSERT" not in conn._cursor.query.upper()


def test_zero_is_explicit_and_omitted_feature_is_not_converted_to_zero(connection):
    conn, allowed = connection
    result = custom_offers.validate_configuration(
        conn, limits={allowed[0]: 0, allowed[1]: 12}, refresh_frequency=None,
    )

    assert result["configuration"]["limits"] == {allowed[0]: 0, allowed[1]: 12}
    assert result["limitStates"] == {allowed[0]: "explicit_zero", allowed[1]: "limited"}
    assert result["saved"] is False
    assert result["priceCalculated"] is False
    assert result["rightsChanged"] is False
    assert result["operatorReviewRequired"] is True

    omitted = custom_offers.validate_configuration(conn, limits={}, refresh_frequency=None)
    assert omitted["configuration"]["limits"] == {}
    assert omitted["limitStates"] == {}


def test_unlimited_is_not_inferred_or_accepted_by_existing_override_contract(connection):
    conn, allowed = connection
    with pytest.raises(custom_offers.CustomOfferError) as error:
        custom_offers.validate_configuration(conn, limits={allowed[0]: None}, refresh_frequency=None)
    assert error.value.code == "invalid_quantity"


def test_unknown_or_catalog_unmapped_features_fail_closed(connection):
    conn, allowed = connection
    with pytest.raises(custom_offers.CustomOfferError) as unknown:
        custom_offers.validate_configuration(conn, limits={"invented_feature": 1}, refresh_frequency=None)
    assert unknown.value.code == "unsupported_feature"

    with pytest.raises(custom_offers.CustomOfferError) as unmapped:
        custom_offers.validate_configuration(conn, limits={allowed[-1]: 1}, refresh_frequency=None)
    assert unmapped.value.code == "feature_unmapped"


@pytest.mark.parametrize("value", [-1, True, 1.5, "4"])
def test_quantities_require_nonnegative_integers(connection, value):
    conn, allowed = connection
    with pytest.raises(custom_offers.CustomOfferError) as error:
        custom_offers.validate_configuration(conn, limits={allowed[0]: value}, refresh_frequency=None)
    assert error.value.code == "invalid_quantity"


def test_refresh_frequency_reuses_only_existing_contract_values(connection):
    conn, _allowed = connection
    for cadence in ("hourly", "daily", "weekly"):
        assert custom_offers.validate_configuration(conn, limits={}, refresh_frequency=cadence)["valid"]
    with pytest.raises(custom_offers.CustomOfferError) as error:
        custom_offers.validate_configuration(conn, limits={}, refresh_frequency="every_5_minutes")
    assert error.value.code == "invalid_refresh_frequency"


def test_configuration_endpoints_require_an_authenticated_tenant(client):
    assert client.get("/billing/custom-offers/configurator").status_code == 401
    assert client.post(
        "/billing/custom-offers/configuration/validate", json={"limits": {}}
    ).status_code == 401


def test_authenticated_configuration_endpoint_is_informational_only(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ai.core.security import TenantContext
    from src.ai.routers import billing

    allowed = tuple(sorted(admin._NUMERIC_CONTRACT_FEATURES))
    conn = Connection([(allowed[0], "records", "max", "billing_period")])
    monkeypatch.setattr(billing.db, "system_connection", lambda: conn)
    app = FastAPI()
    app.include_router(billing.router)
    app.dependency_overrides[billing.get_tenant_context] = lambda: TenantContext("tenant-a", "user-a")

    with TestClient(app) as client:
        catalog = client.get("/billing/custom-offers/configurator")
        validated = client.post(
            "/billing/custom-offers/configuration/validate",
            json={"limits": {allowed[0]: 0}},
        )

    assert catalog.status_code == 200
    assert catalog.json()["initialCheckoutCurrency"] == "USD"
    assert catalog.json()["pricingAvailable"] is False
    assert validated.status_code == 200
    body = validated.json()
    assert body["rightsChanged"] is False
    assert body["priceCalculated"] is False
    assert body["configuration"]["limits"] == {allowed[0]: 0}
