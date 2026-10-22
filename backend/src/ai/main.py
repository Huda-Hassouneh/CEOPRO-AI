"""
KEEL - Service Entrypoint (PENDING_ACTIONS.md #2/#25, RED_FLAGS.md's
Critical "ceopro_admin unconditionally bypasses RLS" entry).

Production-hardening pass (2026-09-15): this file used to hold all 26
endpoints directly. They're now split into routers/ by domain (auth,
health, pricing, sentiment, mpi, rag, extraction, onboarding, dashboard,
sales, competitors) - this file is now just app bootstrap: CORS,
exception handling, pool lifecycle, and wiring every router in. No
endpoint's behavior changed in that split - see each router module for
the real logic, unchanged from what previously lived here.

Before the original version of this file existed, nothing in the deployed
system ever connected to Postgres as anything other than the superuser
ceopro_admin - RLS policies were correct and regression-tested
(tests/test_rls_integration_db.py) but provided zero actual isolation,
since superusers bypass RLS unconditionally regardless of policy
correctness. This is the first real request path that connects as the
restricted ceopro_app role (via db.app_role_connection()) and sets
app.current_tenant_id/app.current_user_id per request.

Auth: POST /auth/login (routers/auth.py) issues the Bearer JWT every other
endpoint's get_tenant_context() dependency (core/security.py) decodes -
previously flagged as a real gap ("no JWT-issuing service... exists
anywhere else in this repo today"), now closed.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.ai import db
from src.ai.core import permissions, tenant_cache, usage
from src.ai.core.entitlements import requires
from src.ai.core.exceptions import register_exception_handlers
from src.ai.core.body_limit import BodySizeLimitMiddleware
from src.ai.core.rate_limit import RateLimitMiddleware
from src.infrastructure.monitoring.error_tracking import init_error_tracking
from src.infrastructure.request_language import RequestLanguageMiddleware
from src.ai.routers import platform
from src.ai.routers import (
    alerts, auth, billing, competitor_enrichment, competitors, dashboard, discovery, extraction, forecasting, health, marketing, mpi, onboarding, operator, pricing, products, rag, reports,
    reviews, sales, sentiment, settings,
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # The connection pool (src/infrastructure/db_pool.py) is still created
    # lazily on first real use (db.py's own established convention -
    # importing/starting this service must never itself require a
    # reachable database, e.g. for `pytest --collect-only` or a health-
    # check-only smoke test). This lifespan's real job is the other half:
    # a clean, explicit shutdown instead of leaving pooled sockets to
    # time out on their own when the process exits.
    # Configuration problems are logged by setting name, never by value
    # (core/config_check.py); start-up continues so health checks can report.
    from src.ai.core import config_check

    config_check.log_findings(logging.getLogger("CEOPRO_AI_MAIN"), config_check.check_environment())
    # Keeps competitor lists current (market_discovery/refresh.py).
    from src.market_scraper.market_discovery import refresh as discovery_refresh

    discovery_refresh.start_background()
    # Daily/weekly alert summaries by email (notification_digest.py).
    from src.ai import notification_digest

    notification_digest.start_background()
    # Stale credit reservations are charged, never left free (billing/maintenance.py).
    from src.ai.billing import maintenance as billing_maintenance

    billing_maintenance.start_background()
    yield
    db.close_pool()


# The service's own loggers (logging.getLogger("CEOPRO_AI_...") in every
# module) had no handler, so Python's last-resort handler dropped
# everything below WARNING: ingestion/sentiment progress and the
# documented local-development fallback of logging auth codes when SMTP
# isn't configured (core/notifications.py) never appeared. Configured once
# here, unless the hosting process already set up logging.
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

# Before the app exists, so start-up errors are reported too (off without SENTRY_DSN).
init_error_tracking("api")

# The interactive docs list every endpoint and its parameters; useful in development, a free map for
# anyone probing a deployed service. API_DOCS_ENABLED=false (render.yaml) turns /docs, /redoc and
# /openapi.json off; the default keeps them on for local development.
_DOCS_ENABLED = os.getenv("API_DOCS_ENABLED", "true").strip().lower() not in ("false", "0", "no")
app = FastAPI(
    title="KEEL Service", lifespan=_lifespan,
    docs_url="/docs" if _DOCS_ENABLED else None, redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)

# Comma-separated list of real origins allowed to call this API from a
# browser - required for the frontend (a separate origin: Vite dev server
# on :5173, or wherever the built app is actually served from in
# production) to be able to call this API at all; without this, every
# browser request fails at the CORS preflight before this service's own
# auth/logic ever runs. Defaults to the Vite dev server's own default
# port, the only origin that's actually true "out of the box" for a fresh
# checkout - a real production origin must be set explicitly, never
# guessed here.
_DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
_cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]

# Requests per minute per company / per address (core/rate_limit.py). Added
# before CORS so CORS wraps it: a 429 still carries the CORS headers the
# browser needs to read it.
app.add_middleware(RateLimitMiddleware)
# Added after the rate limiter so it runs first: an oversized body is refused before anything reads it.
app.add_middleware(BodySizeLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Read by the frontend: how long to wait, and why the assistant couldn't answer.
    expose_headers=["Retry-After", "X-Assistant-Reason", "X-Auth-Reason"],
)

register_exception_handlers(app)
# Interface language (X-App-Language / Accept-Language) for localized names.
app.add_middleware(RequestLanguageMiddleware)


# The interactive API docs load Swagger/ReDoc assets from a CDN and run
# inline scripts, so the lock-down CSP below is not applied to them.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


@app.middleware("http")
async def _security_headers(request, call_next):
    """Headers for a JSON API: no MIME sniffing, never framed, no referrer
    leaking API URLs, HTTPS only (ignored by browsers over plain HTTP, so
    harmless locally), no powerful browser features, and a CSP that lets a
    response do nothing if it is ever opened as a page."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
    if not request.url.path.startswith(_DOCS_PATHS):
        response.headers.setdefault("Content-Security-Policy", _API_CSP)
    return response

_READ_METHODS = ("GET", "HEAD", "OPTIONS")


@app.middleware("http")
async def _forget_cached_views_after_writes(request, call_next):
    """Any write request a company makes (successful or not - a failed one
    may have written part of its work) drops that company's cached read
    models (core/tenant_cache.py), so the next screen shows the change."""
    response = await call_next(request)
    if request.method not in _READ_METHODS:
        tenant_cache.bump(getattr(request.state, "tenant_id", None))
    return response


# Plan modules (core/entitlements.py): a plan without the module gets 402
# NOT_INCLUDED from these routers. The Command Center and reports stay open
# to every plan and simply have no competitor or forecast data on Starter.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(platform.router)
app.include_router(pricing.router)
app.include_router(sentiment.router, dependencies=[requires(usage.MARKET_INTELLIGENCE), Depends(permissions.forbid_read_only_writes)])
app.include_router(mpi.router, dependencies=[requires(usage.MARKET_INTELLIGENCE)])
app.include_router(rag.router)
app.include_router(extraction.router, dependencies=[Depends(permissions.forbid_read_only_writes)])
app.include_router(onboarding.router)
app.include_router(dashboard.router)
app.include_router(sales.router, dependencies=[Depends(permissions.forbid_read_only_writes)])
app.include_router(competitors.router, dependencies=[requires(usage.COMPETITOR_MANAGEMENT), Depends(permissions.forbid_read_only_writes)])
app.include_router(competitor_enrichment.router, dependencies=[requires(usage.COMPETITOR_MANAGEMENT), Depends(permissions.forbid_read_only_writes)])
app.include_router(discovery.router, dependencies=[requires(usage.COMPETITOR_MANAGEMENT), Depends(permissions.forbid_read_only_writes)])
app.include_router(alerts.router)
app.include_router(products.router, dependencies=[Depends(permissions.forbid_read_only_writes)])
app.include_router(settings.router)
app.include_router(operator.router)
app.include_router(marketing.router, dependencies=[Depends(permissions.forbid_read_only_writes)])
app.include_router(reports.router)
app.include_router(reviews.router, dependencies=[Depends(permissions.forbid_read_only_writes)])
app.include_router(billing.router)
app.include_router(forecasting.router, dependencies=[requires(usage.DEMAND_PREDICTION), Depends(permissions.forbid_read_only_writes)])
