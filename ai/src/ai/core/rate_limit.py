"""
KEEL - general API rate limit, on top of the sign-in throttle
(auth_throttle.py) and the assistant's own limit (usage.py).

Counts requests per minute in Redis (one fixed window per minute):
- signed-in requests per company (the tenant in the Bearer token), so one
  company's script or runaway tab can't starve the others -
  API_RATE_LIMIT_PER_COMPANY_PER_MINUTE (default 600);
- anonymous requests per client address (sign-in pages, invitations,
  public endpoints) - API_RATE_LIMIT_PER_IP_PER_MINUTE (default 120).

Over the limit the API answers 429 with Retry-After (seconds to the next
window). The health check, CORS preflights, the Stripe webhook and the API
docs are never limited. Behind a proxy (Render) the client address is the
last X-Forwarded-For entry, which the proxy itself appends; set
API_TRUST_FORWARDED_FOR=true only where such a proxy is in front.

Fails open: if Redis is unreachable requests go through (logged), so an
outage of a protection layer never takes the API down. API_RATE_LIMIT_ENABLED
=false turns it off.
"""
import logging
import os
import time

import jwt
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.ai.core.redis_client import get_redis_client

logger = logging.getLogger("KEEL_RATE_LIMIT")

EXEMPT_PATHS = ("/health", "/billing/webhook", "/docs", "/redoc", "/openapi.json")
_KEY_PREFIX = "keel:ratelimit:"


def _setting(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, redis_factory=None, clock=time.time):
        self.app = app
        self._redis_factory = redis_factory or (lambda: get_redis_client(socket_connect_timeout=0.3, socket_timeout=0.3))
        self._redis = None
        self._clock = clock
        self._jwt_secret = os.getenv("JWT_SECRET")

    def _client(self):
        if self._redis is None:
            self._redis = self._redis_factory()
        return self._redis

    def _identity(self, scope: Scope) -> "tuple[str, int]":
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        authorization = headers.get("authorization", "")
        if authorization.startswith("Bearer ") and self._jwt_secret:
            try:
                claims = jwt.decode(authorization[7:], self._jwt_secret, algorithms=["HS256"])
                if claims.get("tenant_id"):
                    return f"company:{claims['tenant_id']}", int(_setting("API_RATE_LIMIT_PER_COMPANY_PER_MINUTE", "600"))
            except jwt.PyJWTError:
                pass  # counted by address below; the endpoint itself answers 401
        address = scope.get("client")[0] if scope.get("client") else "unknown"
        if _setting("API_TRUST_FORWARDED_FOR", "false").lower() == "true" and headers.get("x-forwarded-for"):
            address = headers["x-forwarded-for"].split(",")[-1].strip() or address
        return f"ip:{address}", int(_setting("API_RATE_LIMIT_PER_IP_PER_MINUTE", "120"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] != "http" or scope.get("method") == "OPTIONS"
                or scope.get("path", "").startswith(EXEMPT_PATHS)
                or _setting("API_RATE_LIMIT_ENABLED", "true").lower() == "false"):
            await self.app(scope, receive, send)
            return
        identity, limit = self._identity(scope)
        now = self._clock()
        window = int(now // 60)
        retry_after = max(1, 60 - int(now % 60))
        try:
            pipe = self._client().pipeline()
            key = f"{_KEY_PREFIX}{identity}:{window}"
            pipe.incr(key)
            pipe.expire(key, 120)
            count = pipe.execute()[0]
        except Exception as err:  # noqa: BLE001 - fail open, see the module docstring
            logger.warning("Rate limit check skipped (Redis unavailable): %s", err)
            self._redis = None
            await self.app(scope, receive, send)
            return
        if count > limit:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please wait a moment and try again."},
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
