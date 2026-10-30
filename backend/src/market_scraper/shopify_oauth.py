"""Tenant-bound Shopify OAuth install flow adapted from the Node KEEL route.

OAuth state is short-lived and single-use in the existing Redis authority;
tokens are exchanged only in the authenticated finish request and stored in
the existing credential vault. This module does not perform canonical writes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import time
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import HTTPException

from src.ai.core import usage
from src.ai.core.redis_client import get_redis_client
from src.market_scraper import data_access
from src.market_scraper.provider_lifecycle import bind_verified_provider_source
from src.market_scraper.shopify import DEFAULT_API_VERSION, ShopifyError, ShopifyGraphQLClient, canonical_shop_domain

_REQUIRED_SCOPES = ("read_products", "read_orders", "read_inventory", "read_locations")
_STATE_TTL = 600
_TICKET_TTL = 120


def _settings() -> tuple[str, str, str, str, str]:
    client_id = os.getenv("SHOPIFY_CLIENT_ID", "").strip()
    secret = os.getenv("SHOPIFY_CLIENT_SECRET", "").strip()
    callback = os.getenv("SHOPIFY_REDIRECT_URI", "").strip()
    from src.infrastructure.public_urls import frontend_origin
    try:
        frontend = frontend_origin()
    except ValueError:
        raise HTTPException(status_code=503, detail='Frontend origin is not configured safely.') from None
    if not client_id or not secret or not callback or not frontend:
        raise HTTPException(status_code=503, detail="Shopify installation is not configured on this server.")
    from urllib.parse import urlsplit
    parts = urlsplit(callback)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise HTTPException(status_code=503, detail="Shopify callback URL is not configured safely.")
    front = urlsplit(frontend)
    local = front.scheme == "http" and front.hostname in {"localhost", "127.0.0.1"}
    if (front.scheme != "https" and not local) or not front.hostname or front.username or front.password or front.query or front.fragment:
        raise HTTPException(status_code=503, detail="Frontend URL is not configured safely.")
    # Match the Node OAuth contract: Shopify's app secret signs state and the
    # callback HMAC. JWT_SECRET remains reserved for KEEL user sessions.
    return client_id, secret, callback, secret, frontend


def _shop(value: str) -> str:
    from urllib.parse import urlsplit
    if isinstance(value, str) and value.strip().lower().startswith("https://"):
        parts = urlsplit(value.strip())
        if parts.username or parts.password or parts.port or parts.query or parts.fragment or parts.path not in ("", "/"):
            raise HTTPException(status_code=422, detail="Use the shop's *.myshopify.com address.")
        value = parts.hostname or ""
    try:
        domain = canonical_shop_domain(value)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Use the shop's *.myshopify.com address.") from exc
    return domain


def begin_authorization(*, tenant_id: str, user_id: str, shop_input: str, sync_frequency_minutes: int = 60,
                       include_test_orders: bool = False) -> dict:
    client_id, _, callback, signing_key, _ = _settings()
    shop = _shop(shop_input)
    nonce = secrets.token_hex(32)
    if isinstance(sync_frequency_minutes, bool) or not isinstance(sync_frequency_minutes, int) \
            or not 15 <= sync_frequency_minutes <= 10080:
        raise HTTPException(status_code=422, detail="Sync frequency is outside the supported range.")
    if not isinstance(include_test_orders, bool):
        raise HTTPException(status_code=422, detail="The test-order setting must be boolean.")
    state = jwt.encode({"tenant_id": str(tenant_id), "user_id": str(user_id), "shop": shop,
                        "nonce": nonce, "aud": "keel-shopify-oauth", "iat": int(time.time()),
                        "sync_frequency_minutes": sync_frequency_minutes,
                        "include_test_orders": include_test_orders,
                        "exp": int(time.time()) + _STATE_TTL}, signing_key, algorithm="HS256")
    state_key = "keel:shopify:oauth:state:" + hashlib.sha256(state.encode()).hexdigest()
    try:
        created = get_redis_client().set(state_key, json.dumps({"tenant_id": str(tenant_id),
                                        "user_id": str(user_id), "shop": shop,
                                        "sync_frequency_minutes": sync_frequency_minutes,
                                        "include_test_orders": include_test_orders}), nx=True, ex=_STATE_TTL)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Shopify authorization state storage is unavailable.") from exc
    if not created:
        raise HTTPException(status_code=503, detail="Could not create a unique Shopify authorization state.")
    requested_scopes = list(_REQUIRED_SCOPES)
    if os.getenv("SHOPIFY_REQUEST_ALL_ORDERS") == "true":
        requested_scopes.append("read_all_orders")
    scopes = ",".join(requested_scopes)
    query = urlencode({"client_id": client_id, "scope": scopes, "redirect_uri": callback, "state": state})
    return {"authorization_url": f"https://{shop}/admin/oauth/authorize?{query}"}


def _verify_callback(params: dict[str, str], signing_key: str) -> dict:
    supplied = params.get("hmac", "")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", supplied):
        raise HTTPException(status_code=400, detail="Shopify callback authentication failed.")
    message = "&".join(f"{key}={params[key]}" for key in sorted(params) if key != "hmac")
    expected = hmac.new(signing_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=400, detail="Shopify callback authentication failed.")
    try:
        timestamp = int(params.get("timestamp", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Shopify callback timestamp is invalid.") from exc
    if abs(int(time.time()) - timestamp) > _STATE_TTL:
        raise HTTPException(status_code=400, detail="Shopify callback has expired.")
    try:
        claims = jwt.decode(params.get("state", ""), signing_key, algorithms=["HS256"],
                            audience="keel-shopify-oauth")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Shopify authorization state is invalid or expired.") from exc
    if claims.get("shop") != _shop(params.get("shop", "")) or not params.get("code"):
        raise HTTPException(status_code=400, detail="Shopify callback does not match its authorization request.")
    if len(params.get("code", "")) > 2048:
        raise HTTPException(status_code=400, detail="Shopify callback code is invalid.")
    return claims


def create_callback_ticket(params: dict[str, str]) -> dict:
    _, _, _, signing_key, frontend = _settings()
    _verify_callback(params, signing_key)
    token = jwt.encode({"callback": params, "aud": "keel-shopify-finish",
                        "iat": int(time.time()), "exp": int(time.time()) + _TICKET_TTL},
                       signing_key, algorithm="HS256")
    return {"ticket": token, "state": params.get("state")}


def _consume_state(state: str, claims: dict) -> None:
    key = "keel:shopify:oauth:state:" + hashlib.sha256(state.encode()).hexdigest()
    expected = json.dumps({"tenant_id": str(claims["tenant_id"]), "user_id": str(claims["user_id"]),
                           "shop": claims["shop"], "sync_frequency_minutes": claims["sync_frequency_minutes"],
                           "include_test_orders": bool(claims.get("include_test_orders", False))})
    script = "local v=redis.call('GET',KEYS[1]); if v==ARGV[1] then redis.call('DEL',KEYS[1]); return 1 else return 0 end"
    try:
        if int(get_redis_client().eval(script, 1, key, expected)) != 1:
            raise HTTPException(status_code=409, detail="Shopify authorization was already used or has expired.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Shopify authorization state storage is unavailable.") from exc


def _exchange_code(shop: str, code: str, client_id: str, secret: str) -> dict:
    url = f"https://{shop}/admin/oauth/access_token"
    try:
        from src.market_scraper.woocommerce import _pinned_transport, _resolve_public_addresses
        addresses = _resolve_public_addresses("https://" + shop, socket.getaddrinfo)
        with httpx.Client(transport=_pinned_transport(addresses[0]), timeout=20,
                          follow_redirects=False, trust_env=False) as client:
            response = client.post(url, json={"client_id": client_id, "client_secret": secret,
                                              "code": code, "expiring": "1"},
                                   headers={"Accept": "application/json"})
        if response.is_redirect or response.status_code != 200:
            raise ValueError("token exchange rejected")
        value = response.json()
        if (not isinstance(value, dict) or not isinstance(value.get("access_token"), str)
                or not isinstance(value.get("refresh_token"), str)
                or not isinstance(value.get("scope"), str)
                or not isinstance(value.get("expires_in"), (int, float))
                or not isinstance(value.get("refresh_token_expires_in"), (int, float))):
            raise ValueError("invalid token response")
        now = int(time.time())
        return {"access_token": value["access_token"], "refresh_token": value["refresh_token"],
                "expires_at": now + int(value["expires_in"]),
                "refresh_expires_at": now + int(value["refresh_token_expires_in"]),
                "scopes": [item.strip() for item in value["scope"].split(",") if item.strip()]}
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Shopify authorization could not be completed.") from exc


def finish_authorization(conn, *, tenant_id: str, user_id: str, ticket: str,
                         api_version: str = DEFAULT_API_VERSION) -> dict:
    client_id, secret, _, signing_key, _ = _settings()
    try:
        payload = jwt.decode(ticket, signing_key, algorithms=["HS256"], audience="keel-shopify-finish")
        params = payload["callback"]
        if not isinstance(params, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in params.items()):
            raise ValueError("invalid callback")
        claims = _verify_callback(params, signing_key)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Shopify authorization ticket has expired.") from exc
    if str(claims.get("tenant_id")) != str(tenant_id) or str(claims.get("user_id")) != str(user_id):
        raise HTTPException(status_code=403, detail="Finish this Shopify connection in the initiating account.")
    _consume_state(params["state"], claims)
    credentials = _exchange_code(claims["shop"], params["code"], client_id, secret)
    if not set(_REQUIRED_SCOPES).issubset(credentials["scopes"]):
        raise HTTPException(status_code=403, detail="The Shopify app is missing a required read permission.")
    if len(api_version) > 12 or not re.fullmatch(r"20[0-9]{2}-(01|04|07|10)", api_version):
        raise HTTPException(status_code=422, detail="Shopify API version is invalid.")
    try:
        client = ShopifyGraphQLClient(claims["shop"], credentials["access_token"], api_version=api_version)
        verification = client.verify_connection()
        ShopifyGraphQLClient.require_scopes(verification, _REQUIRED_SCOPES)
    except ShopifyError as exc:
        raise HTTPException(status_code=502, detail="Shopify could not verify the new installation and permissions.") from exc
    include_test_orders = bool(claims.get("include_test_orders", False))
    if include_test_orders and verification.get("development_store") is not True:
        raise HTTPException(status_code=400, detail="Test orders can only be included from a verified development store.")
    credentials["include_test_orders"] = include_test_orders
    source_id = _bind_shopify_source(conn, tenant_id, user_id, verification, credentials, api_version,
                                     int(claims.get("sync_frequency_minutes", 60)))
    return {"source_id": source_id, "provider": "shopify", "connection_status": "verified",
            "currency_code": verification.get("currency_code"), "api_version": api_version}


def _bind_shopify_source(conn, tenant_id: str, user_id: str, verification: dict,
                         credentials: dict, api_version: str, sync_frequency_minutes: int = 60) -> str:
    shop_id, domain = verification.get("shop_id"), verification.get("shop_domain")
    if not isinstance(shop_id, str) or not isinstance(domain, str):
        raise HTTPException(status_code=502, detail="Shopify returned an invalid store identity.")
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                       ("connected-data-sources:" + str(tenant_id),))
        cursor.execute("SELECT ps.source_id,ds.is_active,ds.collector_config FROM public.keel_provider_sources ps "
                       "JOIN public.data_sources ds ON ds.tenant_id=ps.tenant_id AND ds.source_id=ps.source_id "
                       "WHERE ps.tenant_id=%s::uuid AND ps.provider='shopify' AND ps.verified_store_id=%s "
                       "FOR UPDATE OF ds", (tenant_id, shop_id))
        existing = cursor.fetchone()
    if existing:
        source_id = str(existing[0])
        config = {"provider": "shopify", "shop_domain": domain, "api_version": api_version,
                  "max_pages": 100, "import_test_orders": bool(credentials.get("include_test_orders", False))}
        if existing[2] and existing[2].get("shop_domain") not in (None, domain):
            raise HTTPException(status_code=409, detail="Shopify identity requires operator review.")
        if not existing[1]:
            usage.ensure_capacity(conn, tenant_id, usage.CONNECTED_DATA_SOURCES)
        with conn.cursor() as cursor:
            cursor.execute("UPDATE public.data_sources SET is_active=TRUE,policy_status='ALLOWED',source_url=%s,"
                           "collector_config=%s::jsonb,source_name=%s,sync_frequency_minutes=%s,last_synced_at=NULL "
                           "WHERE tenant_id=%s::uuid AND source_id=%s::uuid",
                           ("https://" + domain, json.dumps(config), domain, sync_frequency_minutes,
                            tenant_id, source_id))
        data_access.set_source_credentials(conn, tenant_id, source_id, credentials, commit=False)
    else:
        usage.ensure_capacity(conn, tenant_id, usage.CONNECTED_DATA_SOURCES)
        source_id = data_access.register_self_service_data_source(
            conn, tenant_id, user_id, domain, "shopify",
            {"provider": "shopify", "shop_domain": domain, "api_version": api_version,
             "max_pages": 100, "import_test_orders": bool(credentials.get("include_test_orders", False))},
            credentials, sync_frequency_minutes, source_url="https://" + domain, commit=False,
        )
    bind_verified_provider_source(conn, tenant_id=tenant_id, source_id=source_id,
                                  provider="shopify", verification=verification)
    return source_id
