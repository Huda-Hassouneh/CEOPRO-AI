from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from fastapi import HTTPException

from src.market_scraper import shopify_oauth as oauth


class _Redis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def eval(self, _script, _count, key, expected):
        if self.values.get(key) == expected:
            del self.values[key]
            return 1
        return 0


@pytest.fixture
def oauth_env(monkeypatch):
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "local-client-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "local-app-secret-with-32-plus-bytes")
    monkeypatch.setenv("SHOPIFY_REDIRECT_URI", "https://local.example.test/onboarding/shopify/callback")
    monkeypatch.setenv("FRONTEND_URL", "https://local.example.test")
    redis = _Redis()
    monkeypatch.setattr(oauth, "get_redis_client", lambda: redis)
    return redis


def _signed_callback(state: str, *, secret: str = "local-app-secret-with-32-plus-bytes", shop: str = "demo.myshopify.com"):
    params = {"code": "auth-code", "shop": shop, "state": state, "timestamp": str(int(oauth.time.time()))}
    canonical = "&".join(f"{key}={params[key]}" for key in sorted(params))
    params["hmac"] = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return params


def test_shopify_authorization_binds_tenant_and_uses_short_lived_single_use_state(oauth_env):
    begun = oauth.begin_authorization(tenant_id="tenant-1", user_id="user-1",
                                      shop_input="https://demo.myshopify.com", sync_frequency_minutes=30,
                                      include_test_orders=True)
    parsed = urlsplit(begun["authorization_url"])
    values = parse_qs(parsed.query)
    assert parsed.netloc == "demo.myshopify.com"
    assert values["scope"] == ["read_products,read_orders,read_inventory,read_locations"]
    state = values["state"][0]
    claims = jwt.decode(state, "local-app-secret-with-32-plus-bytes", algorithms=["HS256"], audience="keel-shopify-oauth")
    assert (claims["tenant_id"], claims["user_id"], claims["shop"], claims["sync_frequency_minutes"]) == (
        "tenant-1", "user-1", "demo.myshopify.com", 30,
    )
    assert claims["include_test_orders"] is True
    assert json.loads(next(iter(oauth_env.values.values())))["include_test_orders"] is True
    assert len(oauth_env.values) == 1
    assert next(iter(oauth_env.ttls.values())) == 600


def test_callback_requires_shopify_hmac_and_returns_short_lived_finish_ticket(oauth_env):
    begun = oauth.begin_authorization(tenant_id="tenant-1", user_id="user-1", shop_input="demo.myshopify.com")
    state = parse_qs(urlsplit(begun["authorization_url"]).query)["state"][0]
    params = _signed_callback(state)
    ticket = oauth.create_callback_ticket(params)
    claims = jwt.decode(ticket["ticket"], "local-app-secret-with-32-plus-bytes", algorithms=["HS256"],
                        audience="keel-shopify-finish")
    assert claims["callback"] == params
    assert ticket["state"] == state
    tampered = {**params, "shop": "other.myshopify.com"}
    with pytest.raises(HTTPException) as exc:
        oauth.create_callback_ticket(tampered)
    assert exc.value.status_code == 400


def test_oauth_finish_rejects_ticket_in_another_tenant_before_consuming_state(oauth_env, monkeypatch):
    begun = oauth.begin_authorization(tenant_id="tenant-1", user_id="user-1", shop_input="demo.myshopify.com")
    state = parse_qs(urlsplit(begun["authorization_url"]).query)["state"][0]
    ticket = oauth.create_callback_ticket(_signed_callback(state))["ticket"]
    with pytest.raises(HTTPException) as exc:
        oauth.finish_authorization(object(), tenant_id="tenant-2", user_id="user-1", ticket=ticket)
    assert exc.value.status_code == 403
    assert len(oauth_env.values) == 1


def test_state_consume_is_single_use_and_tenant_bound(oauth_env):
    begun = oauth.begin_authorization(tenant_id="tenant-1", user_id="user-1", shop_input="demo.myshopify.com")
    state = parse_qs(urlsplit(begun["authorization_url"]).query)["state"][0]
    claims = jwt.decode(state, "local-app-secret-with-32-plus-bytes", algorithms=["HS256"], audience="keel-shopify-oauth")
    oauth._consume_state(state, claims)
    with pytest.raises(HTTPException) as exc:
        oauth._consume_state(state, claims)
    assert exc.value.status_code == 409


def test_optional_all_orders_scope_preserves_existing_configuration_gate(oauth_env, monkeypatch):
    monkeypatch.setenv("SHOPIFY_REQUEST_ALL_ORDERS", "true")
    begun = oauth.begin_authorization(tenant_id="tenant-1", user_id="user-1", shop_input="demo.myshopify.com")
    values = parse_qs(urlsplit(begun["authorization_url"]).query)
    assert values["scope"] == ["read_products,read_orders,read_inventory,read_locations,read_all_orders"]


def test_test_orders_require_verified_development_store_and_keep_the_original_preference(oauth_env, monkeypatch):
    begun = oauth.begin_authorization(tenant_id="tenant-1", user_id="user-1",
                                      shop_input="demo.myshopify.com", include_test_orders=True)
    state = parse_qs(urlsplit(begun["authorization_url"]).query)["state"][0]
    ticket = oauth.create_callback_ticket(_signed_callback(state))["ticket"]
    monkeypatch.setattr(oauth, "_exchange_code", lambda *_: {"access_token": "access", "scopes": list(oauth._REQUIRED_SCOPES)})

    class _Client:
        def __init__(self, *_args, **_kwargs): pass
        def verify_connection(self):
            return {"verified": True, "shop_id": "gid://shopify/Shop/1", "shop_domain": "demo.myshopify.com",
                    "granted_scopes": frozenset(oauth._REQUIRED_SCOPES), "development_store": False}
        @staticmethod
        def require_scopes(value, required):
            if not set(required).issubset(value["granted_scopes"]): raise ValueError("missing scopes")

    monkeypatch.setattr(oauth, "ShopifyGraphQLClient", _Client)
    with pytest.raises(HTTPException) as exc:
        oauth.finish_authorization(object(), tenant_id="tenant-1", user_id="user-1", ticket=ticket)
    assert exc.value.status_code == 400

    begun = oauth.begin_authorization(tenant_id="tenant-1", user_id="user-1",
                                      shop_input="demo.myshopify.com", include_test_orders=True)
    state = parse_qs(urlsplit(begun["authorization_url"]).query)["state"][0]
    ticket = oauth.create_callback_ticket(_signed_callback(state))["ticket"]
    _Client.verify_connection = lambda self: {"verified": True, "shop_id": "gid://shopify/Shop/1",
                                              "shop_domain": "demo.myshopify.com",
                                              "granted_scopes": frozenset(oauth._REQUIRED_SCOPES),
                                              "development_store": True}
    bind = {}
    monkeypatch.setattr(oauth, "_bind_shopify_source",
                        lambda *args, **kwargs: bind.update(args=args, kwargs=kwargs) or "source-1")
    result = oauth.finish_authorization(object(), tenant_id="tenant-1", user_id="user-1", ticket=ticket)
    assert result["source_id"] == "source-1"
    assert bind["args"][4]["include_test_orders"] is True

