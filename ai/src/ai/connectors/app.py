"""Private stateless provider service: uvicorn src.ai.connectors.app:app --port 8002."""
import asyncio
import hashlib
import json
import os
import logging
from uuid import UUID
import jwt
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from dotenv import load_dotenv
from .woocommerce import WooCommerce
from .shopify import Shopify
from .transport import ProviderError

load_dotenv()
app = FastAPI(title='KEEL Store Provider Adapter', docs_url=None, redoc_url=None)
capacity = asyncio.Semaphore(4)

class Query(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: str = Field(default="woocommerce", pattern="^(woocommerce|shopify)$")
    accessToken: str | None = Field(default=None, max_length=4096)
    cursor: str | None = Field(default=None, max_length=4096)
    historyAccess: str = Field(default="recent", pattern="^(all|recent)$")
    includeTestOrders: bool = False
    action: str = Field(pattern='^(detect|verify|products|orders)$')
    url: str = Field(max_length=2048)
    key: str | None = Field(default=None, max_length=64)
    secret: str | None = Field(default=None, max_length=64)
    currency: str = Field(default='JOD', pattern='^[A-Z]{3}$')
    page: int = Field(default=1, ge=1, le=50000)
    since: str | None = None
    until: str | None = None
    exclude: list[str] = Field(default_factory=list, max_length=250)

def execute(query):
    if query.provider == 'shopify':
        provider = Shopify(query.url, query.accessToken, include_test_orders=query.includeTestOrders)
        if query.action == 'verify':
            return provider.verify()
        if query.action == 'products':
            return provider.products(query.cursor, query.currency)
        if query.action == 'orders':
            return provider.orders(query.cursor, query.since, query.until, query.historyAccess)
        raise ProviderError('STORE_INVALID_REQUEST')
    provider = WooCommerce(query.url, query.key, query.secret)
    if query.action == 'detect':
        return provider.detect()
    if not query.key or not query.secret:
        raise ProviderError('STORE_ACCESS_DENIED')
    if query.action == 'verify':
        return provider.verify()
    if query.action == 'products':
        return provider.products(query.page, query.currency, None, None)
    return provider.orders(query.page, query.since, query.until, query.exclude)

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.post('/provider')
async def provider(request: Request):
    secret = os.getenv('STORE_CONNECTOR_SERVICE_SECRET', '')
    if len(secret) < 32:
        raise HTTPException(503, detail='CONNECTOR_NOT_CONFIGURED')
    try:
        authorization = request.headers.get('authorization', '')
        if not authorization.startswith('Bearer '):
            raise ValueError()
        claims = jwt.decode(authorization[7:], secret, algorithms=['HS256'], audience='keel-store-adapter',
                            options={'require': ['exp', 'iat', 'tenant', 'body_hash']})
        UUID(claims['tenant'])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise HTTPException(401, detail='NODE_AUTH_REQUIRED') from None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise HTTPException(413, detail='REQUEST_TOO_LARGE')
    if hashlib.sha256(body).hexdigest() != claims['body_hash']:
        raise HTTPException(401, detail='NODE_AUTH_REQUIRED')
    try:
        query = Query.model_validate_json(bytes(body))
    except ValidationError:
        # Pydantic input errors can include credentials; never return them.
        raise HTTPException(422, detail='INVALID_CONNECTOR_REQUEST') from None
    try:
        async with capacity:
            return await run_in_threadpool(execute, query)
    except ProviderError as exc:
        logging.getLogger('KEEL_STORE_ADAPTER').warning('provider=%s action=%s failed code=%s', query.provider, query.action, exc.code)
        raise HTTPException(422, detail=exc.code) from None
    except Exception:
        raise HTTPException(502, detail='STORE_INVALID_DATA') from None
